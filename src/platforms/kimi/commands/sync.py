"""Sync Kimi — captura + assets + reconcile em uma rodada.

Etapas:
    1. Capture   -> data/raw/Kimi/ (chats + skills + files inline)
    2. Assets    -> binarios via signUrl (skip-existing)
    3. Reconcile -> data/merged/Kimi/ (cumulativo, com preservation)

Flags:
    --no-binaries   pula etapa 2
    --no-reconcile  pula etapa 3
    --full          forca refetch full
    --smoke N       limita N chats
    --account NAME
    --headed        browser visivel

Uso: PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.sync
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from src.assets.vault import AssetVault
from src.assets.runtime import load_asset_runtime, runtime_account_id
from src.platforms.kimi.extractor.asset_downloader import download_assets
from src.platforms.kimi.extractor.auth import load_context
from src.platforms.kimi.extractor.orchestrator import BASE_DIR as RAW_DIR, run_export
from src.platforms.kimi.reconciler import run_reconciliation
from src.accounts import account_data_dir


MERGED_DIR = Path("data/merged/Kimi")


def _account_dir(base: Path, account: str) -> Path:
    return account_data_dir(base, account)


def _section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


async def main(
    args: argparse.Namespace,
    *,
    asset_vault: AssetVault | None = None,
    asset_account_id: str | None = None,
) -> int:
    started = time.time()
    asset_runtime = load_asset_runtime("kimi")
    if asset_vault is None:
        asset_vault = asset_runtime.vault
        asset_account_id = runtime_account_id(
            asset_runtime, "Kimi", args.account, explicit=asset_account_id
        )

    if args.dry_run:
        _section("DRY RUN")
        raw_dir = _account_dir(RAW_DIR, args.account)
        merged_dir = _account_dir(MERGED_DIR, args.account)
        print(f"  Capture seria escrita em: {raw_dir}")
        print(f"  Reconcile seria em:      {merged_dir}")
        print(f"  Modo:                    {'full' if args.full else 'incremental'}")
        print(f"  Etapa 2 (assets):        {'skipped' if args.no_binaries else 'run'}")
        print(f"  Etapa 3 (reconcile):     {'skipped' if args.no_reconcile else 'run'}")
        return 0

    _section("Etapa 1/3 — Capture")
    try:
        raw_dir = await run_export(
            full=args.full,
            smoke_limit=args.smoke,
            account=args.account,
            headless=not args.headed,
            output_dir=_account_dir(RAW_DIR, args.account),
        )
    except Exception as e:
        print(f"\nERRO na captura: {e}")
        return 1
    print(f"\nCapture OK em: {raw_dir}")

    if not args.no_binaries:
        _section("Etapa 2/3 — Assets")
        try:
            context = await load_context(account=args.account, headless=not args.headed)
            try:
                stats = await download_assets(
                    context,
                    raw_dir,
                    asset_vault=asset_vault,
                    account_id=asset_account_id,
                    complete_discovery=args.smoke is None,
                )
            finally:
                await context.close()
            (raw_dir / "assets_log.json").write_text(
                json.dumps(stats, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"  downloaded={stats['downloaded']} "
                  f"skipped={stats['skipped']} "
                  f"errors={len(stats['errors'])}")
        except Exception as e:
            print(f"\nERRO em assets: {e}")
            return 1
    else:
        print("\n--no-binaries setado, pulando etapa 2.")

    if args.no_reconcile:
        print("\n--no-reconcile setado, pulando etapa 3.")
        return 0

    _section("Etapa 3/3 — Reconcile")
    merged_dir = _account_dir(MERGED_DIR, args.account)
    report = run_reconciliation(
        raw_dir,
        merged_dir,
        full=args.full,
        asset_reader=asset_runtime.reader if asset_vault is asset_runtime.vault else None,
        asset_account_id=asset_account_id,
    )
    print(report.summary())
    if report.aborted:
        print(f"  ABORTED: {report.abort_reason}")
        return 2
    if report.warnings:
        print(f"  Warnings ({len(report.warnings)}):")
        for w in report.warnings[:5]:
            print(f"    - {w}")
    print(f"\nMerged em: {merged_dir}")
    print(f"Total elapsed: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-binaries", action="store_true")
    ap.add_argument("--no-reconcile", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--smoke", type=int, default=None)
    ap.add_argument("--account", default="default")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args)))
