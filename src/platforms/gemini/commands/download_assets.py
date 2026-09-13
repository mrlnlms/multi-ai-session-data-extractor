"""Baixa imagens das convs do Gemini raw mais recente de uma conta.

Uso: PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.download_assets --account 1 [raw_dir]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.platforms.gemini.extractor.auth import load_context
from src.platforms.gemini.extractor.api_client import GeminiAPIClient
from src.platforms.gemini.extractor.batchexecute import load_session
from src.platforms.gemini.extractor.asset_downloader import download_assets, extract_deep_research


def _find_latest_raw(account: int) -> Path | None:
    base = Path("data/raw/Gemini Data") / f"account-{account}"
    if not base.exists():
        return None
    candidates = sorted(
        [p for p in base.iterdir() if p.is_dir() and len(p.name) == 16],
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


async def main(raw_dir: Path, account: int, artifacts_only: bool):
    # Deep Research offline (le raw)
    print("Extraindo Deep Research reports...")
    dr = extract_deep_research(raw_dir)
    print(f"  extracted: {dr['extracted']}, skip: {dr['skipped_existing']}, err: {len(dr['errors'])}")

    if artifacts_only:
        return

    context = await load_context(account=account, headless=True)
    try:
        session = await load_session(context)
        client = GeminiAPIClient(context, session)
        stats = await download_assets(client, raw_dir)
        log_path = raw_dir / "assets_log.json"
        log_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
        print(f"\n=== SUMMARY ===")
        print(f"  deep_research: {dr['extracted']}")
        print(f"  images dl:     {stats['downloaded']}")
        print(f"  images skip:   {stats['skipped']}")
        print(f"  errors:        {len(stats['errors'])}")
    finally:
        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("raw_dir", nargs="?", default=None)
    parser.add_argument("--artifacts-only", action="store_true",
                        help="So extrai Deep Research, pula download de imagens")
    args = parser.parse_args()

    if args.raw_dir:
        raw = Path(args.raw_dir)
    else:
        raw = _find_latest_raw(args.account)
        if not raw:
            print(f"ERRO: nenhum raw achado em data/raw/Gemini Data/account-{args.account}/")
            sys.exit(1)
        print(f"Usando raw: {raw}")

    asyncio.run(main(raw, args.account, args.artifacts_only))
