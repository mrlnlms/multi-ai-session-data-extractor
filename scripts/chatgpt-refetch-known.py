"""Refetch state-only de convs ja conhecidas (caminho confiavel quando
discovery upstream retorna parcial).

Pega IDs do `chatgpt_raw.json` atual e refetcha state via
`/conversations/batch` (page.evaluate). NAO depende de listing (`/conversations`).

Tambem chamado AUTOMATICAMENTE pelo `orchestrator.py` como fallback quando
discovery cai >20% vs baseline (substitui o antigo fail-fast). Use o script
standalone quando quiser disparar manualmente fora do sync.

Uso:
  PYTHONPATH=. .venv/bin/python scripts/chatgpt-refetch-known.py [--account default]
                                                                 [--batch-size 10]

Limite upstream do /conversations/batch: 10 entries/request (validado
2026-05-11; antes era 50).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from src.extractors.chatgpt.auth import get_profile_dir
from src.extractors.chatgpt.refetch_known import (
    DEFAULT_BATCH_SIZE,
    refetch_known_via_page,
)


async def refetch(account: str, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
    raw_dir = Path("data/raw/ChatGPT")
    raw_path = raw_dir / "chatgpt_raw.json"
    if not raw_path.exists():
        print(f"raw nao existe: {raw_path}")
        sys.exit(1)

    started_at = datetime.now(timezone.utc)

    profile_dir = get_profile_dir(account)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = await context.new_page()
            await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            stats = await refetch_known_via_page(page, raw_dir, batch_size=batch_size)
        finally:
            await context.close()

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()
    total, updated, errors = stats["total"], stats["updated"], stats["errors"]

    log_entry = {
        "run_started_at": started_at.isoformat(),
        "run_finished_at": finished_at.isoformat(),
        "duration_seconds": duration,
        "mode": "refetch_known",
        "discovery": {"total": total},
        "fetch": {"attempted": total, "succeeded": updated},
        "errors": [],
    }
    log_path = raw_dir / "capture_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    last_md = raw_dir / "LAST_CAPTURE.md"
    last_md.write_text(
        f"# Last capture (refetch_known)\n\n"
        f"- **Quando:** {started_at.isoformat()}\n"
        f"- **Duracao:** {duration:.1f}s\n"
        f"- **Modo:** refetch_known (state-only refresh de IDs conhecidas)\n"
        f"- **Convs atualizadas:** {updated}/{total}\n"
        f"- **Errors:** {errors}\n",
        encoding="utf-8",
    )

    print(f"\nDone. Updated {updated}/{total}, errors={errors}")
    print(f"Raw atualizado: {raw_path}")
    print(f"capture_log.jsonl atualizado")
    print("\nProximo passo:")
    print("  PYTHONPATH=. .venv/bin/python scripts/chatgpt-reconcile.py data/raw/ChatGPT")
    print("  PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="default")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = ap.parse_args()
    asyncio.run(refetch(args.account, args.batch_size))
