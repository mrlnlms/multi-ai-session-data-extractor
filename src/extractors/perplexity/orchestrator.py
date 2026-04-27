"""Orchestrator Perplexity: auth + warmup + discovery + fetch + capture_log.

Default headless=False pra passar Cloudflare challenge (headless detectado como bot).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.perplexity.auth import load_context
from src.extractors.perplexity.api_client import PerplexityAPIClient
from src.extractors.perplexity.discovery import discover
from src.extractors.perplexity.fetcher import fetch_threads


BASE_DIR = Path("data/raw/Perplexity Data")


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


def _tag_map(raw_dir: Path) -> dict[str, str]:
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    with open(disc, encoding="utf-8") as f:
        data = json.load(f)
    return {t["uuid"]: t.get("last_query_datetime", "") or "" for t in data}


async def run_export(
    full: bool = False,
    smoke_limit: int | None = None,
    account: str = "default",
    headless: bool = False,
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = _make_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    prev_raw = None if full else _find_previous_raw(exclude=output_dir)
    prev_map = _tag_map(prev_raw) if prev_raw else {}
    if prev_raw:
        print(f"Modo incremental: cutoff vs {prev_raw.name} ({len(prev_map)} threads conhecidas)")
    else:
        print("Modo full")

    context = await load_context(account=account, headless=headless)
    try:
        page = await context.new_page()
        client = PerplexityAPIClient(context, page)
        await client.warmup()

        threads = await discover(client, output_dir)

        to_fetch = []
        reused = 0
        for t in threads:
            uid = t.get("uuid")
            if not uid:
                continue
            tag = t.get("last_query_datetime", "") or ""
            if uid in prev_map and prev_map[uid] == tag and prev_raw is not None:
                old = prev_raw / "threads" / f"{uid}.json"
                new = output_dir / "threads" / f"{uid}.json"
                new.parent.mkdir(parents=True, exist_ok=True)
                if old.exists():
                    new.write_bytes(old.read_bytes())
                    reused += 1
                    continue
            to_fetch.append(uid)

        if smoke_limit is not None:
            to_fetch = to_fetch[:smoke_limit]
            print(f"SMOKE: limitado a {smoke_limit} threads")

        print(f"Fetching {len(to_fetch)} threads ({reused} reusadas)")
        ok, skipped, errs = await fetch_threads(client, to_fetch, output_dir)

        log = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "full" if full else "incremental",
            "smoke_limit": smoke_limit,
            "headless": headless,
            "previous_raw": prev_raw.name if prev_raw else None,
            "totals": {
                "threads_discovered": len(threads),
                "threads_fetched": ok,
                "threads_reused_incremental": reused,
                "threads_errors": len(errs),
            },
            "errors": {"threads": errs[:50]},
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
