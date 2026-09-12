"""Baixa user uploads + assets gerados (t2i/t2v) + project files do raw Qwen.

Uso:
  python scripts/qwen-download-assets.py [raw_dir]

Sem argumento, usa pasta unica data/raw/Qwen/.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.extractors.qwen.auth import load_context
from src.extractors.qwen.asset_downloader import download_assets
from src.extractors.qwen.orchestrator import BASE_DIR


def _default_raw() -> Path | None:
    if BASE_DIR.exists() and (BASE_DIR / "discovery_ids.json").exists():
        return BASE_DIR
    # Backward compat com layout antigo
    base = Path("data/raw/Qwen Data")
    if not base.exists():
        return None
    legacy = sorted(
        [p for p in base.iterdir() if p.is_dir() and len(p.name) == 16],
        key=lambda p: p.stat().st_mtime,
    )
    return legacy[-1] if legacy else None


async def main(raw_dir: Path, account: str):
    context = await load_context(account=account, headless=True)
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

    raw = Path(args.raw_dir) if args.raw_dir else _default_raw()
    if not raw or not raw.exists():
        print(f"ERRO: nenhum raw achado em {BASE_DIR}/")
        sys.exit(1)
    print(f"Usando raw: {raw}")

    asyncio.run(main(raw, args.account))
