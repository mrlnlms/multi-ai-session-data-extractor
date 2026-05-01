"""Sync Qwen — captura + assets + reconcile em uma rodada.

Espelho de scripts/claude-sync.py.

Etapas:
    1. Capture     -> data/raw/Qwen/ (cumulativo)
    2. Assets      -> binarios (uploads de msgs + projects + t2i/t2v gen)
    3. Reconcile   -> data/merged/Qwen/ (cumulativo, com preservation)

Flags:
    --no-binaries  pula etapa 2
    --no-reconcile pula etapa 3
    --full         forca refetch full
    --smoke N
    --account NAME

Uso: python scripts/qwen-sync.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from src.extractors.qwen.asset_downloader import download_assets
from src.extractors.qwen.auth import load_context
from src.extractors.qwen.orchestrator import BASE_DIR as RAW_DIR, run_export
from src.reconcilers.qwen import run_reconciliation


MERGED_DIR = Path("data/merged/Qwen")


def _section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


async def _run_assets(raw_dir: Path, account: str) -> dict:
    print("Baixando assets (uploads + projects + generated)...")
    context = await load_context(account=account, headless=True)
    try:
        stats = await download_assets(context, raw_dir)
    finally:
        await context.close()
    log_path = raw_dir / "assets_log.json"
    log_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
    print(f"  downloaded={stats['downloaded']} "
          f"skipped={stats['skipped']} "
          f"err={len(stats['errors'])}")
    return stats


async def main(args: argparse.Namespace) -> int:
    started = time.time()

    if args.dry_run:
        _section("DRY RUN")
        print(f"  Capture seria escrita em: {RAW_DIR}")
        print(f"  Reconcile seria em:      {MERGED_DIR}")
        print(f"  Modo:                    {'full' if args.full else 'incremental'}")
        print(f"  Etapa 2 (assets):        {'skipped' if args.no_binaries else 'run'}")
        print(f"  Etapa 3 (reconcile):     {'skipped' if args.no_reconcile else 'run'}")
        return 0

    _section("Etapa 1/3 — Capture")
    try:
        raw_dir = await run_export(
            full=args.full, smoke_limit=args.smoke, account=args.account,
        )
    except Exception as e:
        print(f"\nERRO na captura: {e}")
        return 1
    print(f"\nCapture OK em: {raw_dir}")

    if not args.no_binaries:
        _section("Etapa 2/3 — Assets")
        try:
            await _run_assets(raw_dir, account=args.account)
        except Exception as e:
            print(f"\nERRO em assets: {e}")
            return 1
    else:
        print("\n--no-binaries setado, pulando etapa 2.")

    if args.no_reconcile:
        print("\n--no-reconcile setado, pulando etapa 3.")
        return 0

    _section("Etapa 3/3 — Reconcile")
    report = run_reconciliation(raw_dir, MERGED_DIR)
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
    ap.add_argument("--no-binaries", action="store_true", help="Pula etapa 2 (assets)")
    ap.add_argument("--no-reconcile", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--smoke", type=int, default=None)
    ap.add_argument("--account", default="default")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args)))
