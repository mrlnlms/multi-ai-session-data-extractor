"""Download dos files inline em chat.files[] (Kimi).

Pre-requisito: ``python -m src.platforms.kimi.commands.export`` rodou e populou conversations/.

Uso:
    PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.download_assets
    PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.download_assets --no-skip
"""

import argparse
import asyncio
import json

from src.platforms.kimi.extractor.auth import load_context
from src.platforms.kimi.extractor.asset_downloader import download_assets
from src.platforms.kimi.extractor.orchestrator import BASE_DIR


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
        for e in stats["errors"][:5]:
            print(f"  {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-skip", action="store_true")
    ap.add_argument("--account", default="default")
    args = ap.parse_args()
    asyncio.run(main(args))
