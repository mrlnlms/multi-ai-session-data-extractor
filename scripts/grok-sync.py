"""Sync Grok — captura + reconcile em uma rodada.

Etapas:
    1. Capture   -> data/raw/Grok/ (cumulativo)
    2. Reconcile -> data/merged/Grok/ (cumulativo, com preservation)

Flags:
    --no-reconcile  pula etapa 2
    --full          forca refetch full
    --smoke N       limita N convs
    --account NAME
    --headed        browser visivel

Uso: python scripts/grok-sync.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from src.extractors.grok.orchestrator import BASE_DIR as RAW_DIR, run_export
from src.reconcilers.grok import run_reconciliation


MERGED_DIR = Path("data/merged/Grok")


def _section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


async def main(args: argparse.Namespace) -> int:
    started = time.time()

    if args.dry_run:
        _section("DRY RUN")
        print(f"  Capture seria escrita em: {RAW_DIR}")
        print(f"  Reconcile seria em:      {MERGED_DIR}")
        print(f"  Modo:                    {'full' if args.full else 'incremental'}")
        print(f"  Etapa 2 (reconcile):     {'skipped' if args.no_reconcile else 'run'}")
        return 0

    _section("Etapa 1/2 — Capture")
    try:
        raw_dir = await run_export(
            full=args.full,
            smoke_limit=args.smoke,
            account=args.account,
            headless=not args.headed,
        )
    except Exception as e:
        print(f"\nERRO na captura: {e}")
        return 1
    print(f"\nCapture OK em: {raw_dir}")

    if args.no_reconcile:
        print("\n--no-reconcile setado, pulando etapa 2.")
        return 0

    _section("Etapa 2/2 — Reconcile")
    report = run_reconciliation(raw_dir, MERGED_DIR, full=args.full)
    print(report.summary())
    if report.aborted:
        print(f"  ABORTED: {report.abort_reason}")
        return 2
    if report.warnings:
        print(f"  Warnings ({len(report.warnings)}):")
        for w in report.warnings[:5]:
            print(f"    - {w}")
    print(f"\nMerged em: {MERGED_DIR}")
    print(f"Total elapsed: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-reconcile", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--smoke", type=int, default=None)
    ap.add_argument("--account", default="default")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args)))
