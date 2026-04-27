"""Orchestrator DeepSeek: auth + warmup + discovery + fetch + capture_log.

Raw vai pra data/raw/DeepSeek Data/<YYYY-MM-DDTHH-MM>/:
  - discovery_ids.json
  - conversations/<conv_id>.json (biz_data do history_messages)
  - capture_log.json

Modo default: incremental — compara updated_at com dump anterior.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.deepseek.auth import load_context
from src.extractors.deepseek.api_client import DeepSeekAPIClient
from src.extractors.deepseek.discovery import discover
from src.extractors.deepseek.fetcher import fetch_conversations


BASE_DIR = Path("data/raw/DeepSeek Data")


def _make_output_dir() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
    return BASE_DIR / ts


def _find_previous_raw(exclude: Path) -> Path | None:
    if not BASE_DIR.exists():
        return None
    candidates = [
        p for p in BASE_DIR.iterdir()
        if p.is_dir() and len(p.name) == 16 and "T" in p.name
        and p.resolve() != exclude.resolve()
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _conv_tag_map(raw_dir: Path) -> dict[str, float]:
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    with open(disc, encoding="utf-8") as f:
        data = json.load(f)
    return {c["id"]: c.get("updated_at", 0) or 0 for c in data}


async def run_export(
    full: bool = False,
    smoke_limit: int | None = None,
    account: str = "default",
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = _make_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    prev_raw = None if full else _find_previous_raw(exclude=output_dir)
    prev_map = _conv_tag_map(prev_raw) if prev_raw else {}
    if prev_raw:
        print(f"Modo incremental: cutoff vs {prev_raw.name} ({len(prev_map)} convs conhecidas)")
    else:
        print("Modo full")

    context = await load_context(account=account, headless=True)
    try:
        page = await context.new_page()
        client = DeepSeekAPIClient(context, page)
        await client.warmup()

        sessions = await discover(client, output_dir)

        to_fetch = []
        reused = 0
        for s in sessions:
            sid = s["id"]
            upd = s.get("updated_at") or 0
            if sid in prev_map and prev_map[sid] == upd and prev_raw is not None:
                old = prev_raw / "conversations" / f"{sid}.json"
                new = output_dir / "conversations" / f"{sid}.json"
                new.parent.mkdir(parents=True, exist_ok=True)
                if old.exists():
                    new.write_bytes(old.read_bytes())
                    reused += 1
                    continue
            to_fetch.append(sid)

        if smoke_limit is not None:
            to_fetch = to_fetch[:smoke_limit]
            print(f"SMOKE: limitado a {smoke_limit} convs")

        print(f"Fetching {len(to_fetch)} convs ({reused} reusadas)")
        ok, skipped, errs = await fetch_conversations(client, to_fetch, output_dir)

        log = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "full" if full else "incremental",
            "smoke_limit": smoke_limit,
            "previous_raw": prev_raw.name if prev_raw else None,
            "totals": {
                "conversations_discovered": len(sessions),
                "conversations_fetched": ok,
                "conversations_reused_incremental": reused,
                "conversations_errors": len(errs),
            },
            "errors": {"conversations": errs[:50]},
        }
        with open(output_dir / "capture_log.json", "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        return output_dir
    finally:
        await context.close()
