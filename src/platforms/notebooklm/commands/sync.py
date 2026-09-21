"""Sync NotebookLM — captura + assets + reconcile para uma conta explicita.

Etapas (por conta):
    1. Capture     -> data/raw/NotebookLM/account-{N}/ (cumulativo)
    2. Assets      -> binarios (audio MP4, video MP4, slide PDF+PPTX, source PDFs)
    3. Reconcile   -> data/merged/NotebookLM/account-{N}/

Flags:
    --account KEY conta indicada pelo orquestrador compartilhado
    --no-binaries     pula etapa 2 (assets)
    --no-reconcile    pula etapa 3
    --full            forca refetch full (propagado pro reconcile — bug preventivo #3)
    --smoke N         smoke: N notebooks por conta
    --dry-run

Uso: PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.sync --account 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Mapping
from src.accounts import capturable_account_key

from src.assets.vault import AssetVault
from src.assets.reader import AssetReader
from src.assets.runtime import load_asset_runtime, runtime_account_id
from src.platforms.notebooklm.extractor.auth import ACCOUNT_LANG, load_context
from src.platforms.notebooklm.extractor.api_client import NotebookLMClient
from src.platforms.notebooklm.extractor.batchexecute import load_session
from src.platforms.notebooklm.extractor.asset_downloader import (
    download_assets, fetch_text_artifacts, save_notes_and_mindmaps,
)
from src.platforms.notebooklm.extractor.orchestrator import run_export
from src.platforms.notebooklm.reconciler import run_reconciliation


MERGED_BASE = Path("data/merged/NotebookLM")


def _section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


async def _run_assets(
    raw_dir: Path,
    account: str,
    *,
    asset_vault: AssetVault | None = None,
    asset_account_id: str | None = None,
) -> dict:
    """Etapa 2: notes/mind_maps offline + binarios online + text artifacts."""
    context = await load_context(account=account, headless=True)
    try:
        session = await load_session(context)
        client = NotebookLMClient(context, session, hl=ACCOUNT_LANG.get(account, "pt-BR"))
        # Offline: notes + mind_maps
        nm_stats = save_notes_and_mindmaps(
            raw_dir, asset_vault=asset_vault, account_id=asset_account_id
        )
        # Online: binarios
        stats = await download_assets(
            client,
            raw_dir,
            asset_vault=asset_vault,
            account_id=asset_account_id,
            complete_discovery=False,
        )
        download_errors = list(stats.get("errors", []))
        # Online: text artifacts (types 2/4/7/9 via v9rmvd)
        text_stats = await fetch_text_artifacts(
            client, raw_dir, asset_vault=asset_vault, account_id=asset_account_id
        )
        # Merge
        stats.update(nm_stats)
        stats.update(text_stats)
        stats["errors"] = (
            download_errors
            + list(nm_stats.get("errors", []))
            + list(text_stats.get("errors", []))
        )
    finally:
        await context.close()

    log_path = raw_dir / "assets_log.json"
    log_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
    print(f"  audios dl={stats.get('audios_downloaded',0)} skip={stats.get('audios_skipped',0)}")
    print(f"  videos dl={stats.get('videos_downloaded',0)} skip={stats.get('videos_skipped',0)}")
    print(f"  slide decks dl={stats.get('slide_decks_downloaded',0)} skip={stats.get('slide_decks_skipped',0)}")
    print(f"  pages dl={stats.get('pages_downloaded',0)} skip={stats.get('pages_skipped',0)}")
    print(f"  text artifacts={stats.get('text_artifacts_fetched',0)} skip={stats.get('text_artifacts_skipped',0)}")
    print(f"  notes={stats.get('notes_saved',0)} mind_maps={stats.get('mind_maps_saved',0)}")
    print(f"  errors={len(stats['errors'])}")
    return stats


async def _sync_account(
    args: argparse.Namespace,
    account: str,
    *,
    asset_vault: AssetVault | None = None,
    asset_account_id: str | None = None,
    asset_reader: AssetReader | None = None,
) -> int:
    _section(f"ACCOUNT {account}")
    _section(f"Etapa 1/3 — Capture (account {account})")
    try:
        raw_dir = await run_export(account=account, full=args.full, smoke_limit=args.smoke)
    except Exception as e:
        print(f"\nERRO na captura account {account}: {e}")
        return 1
    print(f"\nCapture OK em: {raw_dir}")

    if not args.no_binaries:
        _section(f"Etapa 2/3 — Assets (account {account})")
        try:
            await _run_assets(
                raw_dir,
                account=account,
                asset_vault=asset_vault,
                asset_account_id=asset_account_id,
            )
        except Exception as e:
            print(f"\nERRO em assets account {account}: {e}")
            return 1
    else:
        print("\n--no-binaries setado, pulando etapa 2.")

    if args.no_reconcile:
        print("\n--no-reconcile setado, pulando etapa 3.")
        return 0

    _section(f"Etapa 3/3 — Reconcile (account {account})")
    merged_dir = MERGED_BASE / f"account-{account}"
    report = run_reconciliation(
        raw_dir,
        merged_dir,
        full=args.full,
        asset_reader=asset_reader,
        asset_account_id=asset_account_id,
    )
    if report.aborted:
        print(f"  ABORTED: {report.abort_reason}")
        return 2
    print(f"\n{report.summary()}")
    if report.warnings:
        print(f"  Warnings ({len(report.warnings)}):")
        for w in report.warnings[:5]:
            print(f"    - {w}")
    print(f"\nMerged em: {merged_dir}")
    return 0


async def main(
    args: argparse.Namespace,
    *,
    asset_vault: AssetVault | None = None,
    asset_account_ids: Mapping[str, str] | None = None,
) -> int:
    started = time.time()
    asset_runtime = load_asset_runtime("notebooklm")
    if args.account is None:
        raise ValueError("NotebookLM sync requires an explicit account")

    if args.dry_run:
        _section("DRY RUN")
        accounts = [args.account]
        for acc in accounts:
            print(f"  Account {acc}:")
            print(f"    Capture:   data/raw/NotebookLM/account-{acc}/")
            print(f"    Reconcile: data/merged/NotebookLM/account-{acc}/")
        print(f"  Modo:        {'full' if args.full else 'incremental'}")
        print(f"  Etapa 2:     {'skipped' if args.no_binaries else 'run'}")
        print(f"  Etapa 3:     {'skipped' if args.no_reconcile else 'run'}")
        return 0

    accounts = [args.account]
    if asset_vault is None:
        asset_vault = asset_runtime.vault
        asset_account_ids = {
            acc: runtime_account_id(
                asset_runtime,
                "NotebookLM",
                f"account-{acc}",
                explicit=(asset_account_ids or {}).get(acc),
            )
            for acc in accounts
        }
    overall = 0
    for acc in accounts:
        rc = await _sync_account(
            args,
            acc,
            asset_vault=asset_vault,
            asset_account_id=(asset_account_ids or {}).get(acc),
            asset_reader=asset_runtime.reader if asset_vault is asset_runtime.vault else None,
        )
        if rc != 0:
            overall = rc

    print()
    print(f"Total elapsed: {time.time() - started:.1f}s")
    return overall


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", type=capturable_account_key, required=True,
                    help="Conta explicita a capturar")
    ap.add_argument("--no-binaries", action="store_true", help="Pula etapa 2 (assets)")
    ap.add_argument("--no-reconcile", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--smoke", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args)))
