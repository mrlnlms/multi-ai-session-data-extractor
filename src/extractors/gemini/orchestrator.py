"""Orchestrator: auth + discovery + fetch + capture_log.

Modo default: incremental (re-fetch so convs com created_at_secs != conhecido).
Assets em script separado (scripts/gemini-download-assets.py).

Raw vai pra data/raw/Gemini Data/account-{N}/YYYY-MM-DDTHH-MM/ — preserva
estrutura multi-conta existente.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.gemini.auth import load_context
from src.extractors.gemini.api_client import GeminiAPIClient
from src.extractors.gemini.batchexecute import load_session
from src.extractors.gemini.discovery import discover
from src.extractors.gemini.fetcher import fetch_conversations


def _account_dir(account: int) -> Path:
    return Path("data/raw/Gemini Data") / f"account-{account}"


def _make_output_dir(account: int) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
    return _account_dir(account) / ts


def _find_previous_raw(account: int, exclude: Path) -> Path | None:
    base = _account_dir(account)
    if not base.exists():
        return None
    candidates = [
        p for p in base.iterdir()
        if p.is_dir() and len(p.name) == 16 and "T" in p.name  # formato yyyy-mm-ddThh-mm
        and p.resolve() != exclude.resolve()
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _conv_tag_map(raw_dir: Path) -> dict[str, int]:
    """Le discovery_ids.json do raw anterior e retorna uuid -> created_at_secs."""
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    with open(disc, encoding="utf-8") as f:
        data = json.load(f)
    return {c["uuid"]: c.get("created_at_secs", 0) or 0 for c in data}


async def run_export(
    account: int = 1,
    full: bool = False,
    smoke_limit: int | None = None,
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = _make_output_dir(account)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    prev_raw = None if full else _find_previous_raw(account, exclude=output_dir)
    prev_map = _conv_tag_map(prev_raw) if prev_raw else {}
    if prev_raw:
        print(f"Modo incremental: cutoff vs {prev_raw.name} ({len(prev_map)} convs conhecidas)")
    else:
        print("Modo full")

    context = await load_context(account=account, headless=True)
    try:
        session = await load_session(context)
        client = GeminiAPIClient(context, session)

        # Discovery
        convs = await discover(client, output_dir)

        # Cutoff incremental
        convs_to_fetch = []
        reused = 0
        for c in convs:
            uid = c["uuid"]
            secs = c.get("created_at_secs") or 0
            if uid in prev_map and prev_map[uid] == secs and prev_raw is not None:
                # Copia do raw anterior
                old_file = prev_raw / "conversations" / f"{uid}.json"
                new_file = output_dir / "conversations" / f"{uid}.json"
                new_file.parent.mkdir(parents=True, exist_ok=True)
                if old_file.exists():
                    new_file.write_bytes(old_file.read_bytes())
                    reused += 1
                    continue
            convs_to_fetch.append(uid)

        if smoke_limit is not None:
            convs_to_fetch = convs_to_fetch[:smoke_limit]
            print(f"SMOKE: limitado a {smoke_limit} convs")

        print(f"Fetching {len(convs_to_fetch)} convs ({reused} reusadas)")
        conv_ok, conv_skip, conv_errs = await fetch_conversations(
            client, convs_to_fetch, output_dir, concurrency=2
        )

        log = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "mode": "full" if full else "incremental",
            "smoke_limit": smoke_limit,
            "previous_raw": prev_raw.name if prev_raw else None,
            "totals": {
                "conversations_discovered": len(convs),
                "conversations_fetched": conv_ok,
                "conversations_reused_incremental": reused,
                "conversations_errors": len(conv_errs),
            },
            "errors": {"conversations": conv_errs[:50]},
        }
        with open(output_dir / "capture_log.json", "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        print(f"Proximo passo: python scripts/gemini-download-assets.py --account {account}")
        return output_dir
    finally:
        await context.close()
