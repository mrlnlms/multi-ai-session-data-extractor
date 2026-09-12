"""Download de assets NotebookLM (todos os 9 tipos de outputs).

Pasta unica cumulativa per-account — skip-existing nos proprios paths
elimina necessidade de copia entre runs.

Uso:
    python scripts/notebooklm-download-assets.py --account 1
    python scripts/notebooklm-download-assets.py --account 2
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.extractors.notebooklm.auth import load_context, VALID_ACCOUNTS, ACCOUNT_LANG
from src.extractors.notebooklm.api_client import NotebookLMClient
from src.extractors.notebooklm.batchexecute import load_session
from src.extractors.notebooklm.asset_downloader import (
    download_assets, fetch_text_artifacts, save_notes_and_mindmaps,
)
from src.extractors.notebooklm.orchestrator import BASE_DIR as RAW_BASE


async def main(raw_dir: Path, account: str):
    context = await load_context(account, headless=True)
    try:
        session = await load_session(context)
        client = NotebookLMClient(context, session, hl=ACCOUNT_LANG[account])
        # Notes + Mind Maps: offline (ja estao no cFji9 capturado)
        nm_stats = save_notes_and_mindmaps(raw_dir)
        # Downloads de midia (audios, videos, slide decks, pages)
        stats = await download_assets(client, raw_dir)
        # Text artifacts (types 2/4/7/9) via v9rmvd
        text_stats = await fetch_text_artifacts(client, raw_dir)
        # Merge
        stats.update(nm_stats)
        stats.update(text_stats)
        stats["errors"].extend(nm_stats.get("errors", []))
        stats["errors"].extend(text_stats.get("errors", []))
        log_path = raw_dir / "assets_log.json"
        log_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
        print(f"\n=== SUMMARY ===")
        print(f"  audios dl:      {stats['audios_downloaded']} skip: {stats['audios_skipped']}")
        print(f"  videos dl:      {stats.get('videos_downloaded',0)} skip: {stats.get('videos_skipped',0)}")
        print(f"  slide decks dl: {stats.get('slide_decks_downloaded',0)} skip: {stats.get('slide_decks_skipped',0)}")
        print(f"  pages dl:       {stats['pages_downloaded']} skip: {stats['pages_skipped']}")
        print(f"  text artifacts: {stats.get('text_artifacts_fetched',0)} skip: {stats.get('text_artifacts_skipped',0)}")
        print(f"  notes saved:    {stats.get('notes_saved',0)} skip: {stats.get('notes_skipped',0)}")
        print(f"  mind maps:      {stats.get('mind_maps_saved',0)} skip: {stats.get('mind_maps_skipped',0)}")
        print(f"  errors:         {len(stats['errors'])}")
    finally:
        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=list(VALID_ACCOUNTS))
    parser.add_argument("raw_dir", nargs="?", default=None,
                        help="Override do raw dir (default: data/raw/NotebookLM/account-{N}/)")
    args = parser.parse_args()
    raw = Path(args.raw_dir) if args.raw_dir else RAW_BASE / f"account-{args.account}"
    if not raw.exists():
        print(f"Raw nao existe: {raw}. Rode notebooklm-export primeiro.")
        sys.exit(1)
    print(f"Usando raw: {raw}")
    asyncio.run(main(raw, args.account))
