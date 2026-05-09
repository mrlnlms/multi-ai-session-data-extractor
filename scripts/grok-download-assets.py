"""Download dos asset binarios do Grok via assets.grok.com.

Pre-requisito: scripts/grok-export.py rodou e populou assets.json.

Uso:
    python scripts/grok-download-assets.py
    python scripts/grok-download-assets.py --no-skip   # re-baixa tudo
"""

import argparse
import asyncio
import json
from pathlib import Path

from src.extractors.grok.auth import load_context
from src.extractors.grok.asset_downloader import download_assets
from src.extractors.grok.orchestrator import BASE_DIR


async def main(args):
    context = await load_context(account=args.account, headless=True)
    try:
        stats = await download_assets(
            context, BASE_DIR, skip_existing=not args.no_skip
        )
    finally:
        await context.close()

    log_path = BASE_DIR / "assets_log.json"
    log_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nDownloaded={stats['downloaded']} "
          f"skipped={stats['skipped']} "
          f"errors={len(stats['errors'])}")
    if stats["errors"]:
        print("First errors:")
        for e in stats["errors"][:5]:
            print(f"  {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-skip", action="store_true", help="Re-baixa mesmo se ja existe")
    ap.add_argument("--account", default="default")
    args = ap.parse_args()
    asyncio.run(main(args))
