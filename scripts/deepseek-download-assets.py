"""Baixa user uploads de um raw DeepSeek via /api/v0/file/preview.

Uso:
  python scripts/deepseek-download-assets.py [raw_dir]

Sem argumento, usa o raw mais recente em data/raw/DeepSeek Data/.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.extractors.deepseek.auth import load_context, HOME_URL
from src.extractors.deepseek.asset_downloader import download_assets


def _find_latest_raw() -> Path | None:
    base = Path("data/raw/DeepSeek Data")
    if not base.exists():
        return None
    candidates = sorted(
        [p for p in base.iterdir() if p.is_dir() and len(p.name) == 16 and "T" in p.name],
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


async def main(raw_dir: Path, account: str):
    context = await load_context(account=account, headless=True)
    try:
        page = await context.new_page()
        # Warmup pra carregar localStorage
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        raw_token = await page.evaluate("() => localStorage.getItem('userToken')")
        if not raw_token:
            print("ERRO: localStorage.userToken vazio — profile nao logado?")
            return
        token = json.loads(raw_token)["value"]

        stats = await download_assets(context, page, token, raw_dir)
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

    raw = Path(args.raw_dir) if args.raw_dir else _find_latest_raw()
    if not raw or not raw.exists():
        print("ERRO: nenhum raw achado em data/raw/DeepSeek Data/")
        sys.exit(1)
    print(f"Usando raw: {raw}")

    asyncio.run(main(raw, args.account))
