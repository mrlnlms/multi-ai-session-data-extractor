"""Sync DeepSeek — captura + reconcile em uma rodada.

Espelho do comando `python -m src.platforms.qwen.commands.sync`. DeepSeek nao tem assets/projects, so threads.

Etapas:
    1. Capture     -> data/raw/DeepSeek/ (cumulativo)
    2. Reconcile   -> data/merged/DeepSeek/ (cumulativo, com preservation)
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
from src.platforms.deepseek.extractor.asset_downloader import download_assets
from src.platforms.deepseek.extractor.auth import HOME_URL, load_context
from src.platforms.deepseek.extractor.orchestrator import BASE_DIR as RAW_DIR, run_export
from src.platforms.deepseek.reconciler import run_reconciliation
from src.accounts import account_data_dir


MERGED_DIR = Path("data/merged/DeepSeek")


def _account_dir(base: Path, account: str) -> Path:
    return account_data_dir(base, account)


def _section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


async def _run_assets(
    raw_dir: Path,
    account: str,
    *,
    asset_vault: AssetVault,
    asset_account_id: str | None,
    complete_discovery: bool,
) -> dict:
    context = await load_context(account=account, headless=True)
    try:
        page = await context.new_page()
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        raw_token = await page.evaluate("() => localStorage.getItem('userToken')")
        if not raw_token:
            raise RuntimeError("localStorage.userToken is empty")
        token = json.loads(raw_token)["value"]
        return await download_assets(
            context,
            page,
            token,
            raw_dir,
            asset_vault=asset_vault,
            account_id=asset_account_id,
            complete_discovery=complete_discovery,
        )
    finally:
        await context.close()


async def main(
    args: argparse.Namespace,
    *,
    asset_vault: AssetVault | None = None,
    asset_account_id: str | None = None,
) -> int:
    started = time.time()
    asset_runtime = load_asset_runtime("deepseek")
    if asset_vault is None:
        asset_vault = asset_runtime.vault
        asset_account_id = runtime_account_id(
            asset_runtime, "DeepSeek", args.account, explicit=asset_account_id
        )

    if args.dry_run:
        _section("DRY RUN")
        raw_dir = _account_dir(RAW_DIR, args.account)
        merged_dir = _account_dir(MERGED_DIR, args.account)
        print(f"  Capture seria escrita em: {raw_dir}")
        print(f"  Reconcile seria em:      {merged_dir}")
        print(f"  Modo:                    {'full' if args.full else 'incremental'}")
        print(f"  Reconcile:               {'skipped' if args.no_reconcile else 'run'}")
        return 0

    _section("Etapa 1/2 — Capture")
    try:
        raw_dir = await run_export(
            full=args.full, smoke_limit=args.smoke, account=args.account,
            output_dir=_account_dir(RAW_DIR, args.account),
        )
    except Exception as e:
        print(f"\nERRO na captura: {e}")
        return 1
    print(f"\nCapture OK em: {raw_dir}")

    if asset_vault is not None and not args.no_binaries:
        _section("Vault asset capture (temporary rollout)")
        try:
            await _run_assets(
                raw_dir,
                args.account,
                asset_vault=asset_vault,
                asset_account_id=asset_account_id,
                complete_discovery=args.smoke is None,
            )
        except Exception as e:
            print(f"\nERRO em assets: {e}")
            return 1

    if args.no_reconcile:
        print("\n--no-reconcile setado, pulando etapa 2.")
        return 0

    _section("Etapa 2/2 — Reconcile")
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
    ap.add_argument("--no-reconcile", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--no-binaries", action="store_true",
                    help="(no-op pra DeepSeek: nao tem assets/projects, so threads)")
    ap.add_argument("--smoke", type=int, default=None)
    ap.add_argument("--account", default="default")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args)))
