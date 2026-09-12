"""Baixa user uploads + featured images de um raw Perplexity.

Uso:
  python scripts/perplexity-download-assets.py [raw_dir]

Filtra URLs: so baixa dominios da Perplexity (ppl-ai-file-upload, pplx-res.cloudinary).
URLs externas (imagens de sites web citados em respostas) NAO sao baixadas.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.extractors.perplexity.auth import load_context
from src.extractors.perplexity.asset_downloader import download_assets
from src.accounts import account_data_dir


async def main(raw_dir: Path, account: str):
    # headless=False porque precisa passar Cloudflare pra chamar
    # /rest/file-repository/download-attachment que gera URLs S3 frescas.
    context = await load_context(account=account, headless=False)
    try:
        stats = await download_assets(context, raw_dir)
        log_path = raw_dir / "assets_log.json"
        log_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
        print("\n=== SUMMARY ===")
        print(f"  downloaded: {stats['downloaded']}")
        print(f"  skipped:    {stats['skipped']}")
        print(f"  errors:     {len(stats['errors'])}")
    finally:
        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_dir", nargs="?", default=None)
    parser.add_argument("--account", type=str, default="default")
    args = parser.parse_args()

    raw = Path(args.raw_dir) if args.raw_dir else account_data_dir(Path("data/raw/Perplexity"), args.account)
    if not raw or not raw.exists():
        print("ERRO: nenhum raw achado em data/raw/Perplexity/")
        sys.exit(1)
    print(f"Usando raw: {raw}")

    asyncio.run(main(raw, args.account))
