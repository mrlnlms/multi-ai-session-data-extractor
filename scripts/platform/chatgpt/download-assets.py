"""Download de imagens + project files do ChatGPT via Playwright intercept.

Uso:
    python scripts/chatgpt-download-assets.py [raw_dir]
                                              [--only-conv ID] [--include-projects]

Exemplos:
    # Todas as convs com imagens do raw mais recente
    python scripts/chatgpt-download-assets.py "data/raw/ChatGPT Data 2026-04-23T12-40"

    # So 1 conv (pra teste)
    python scripts/chatgpt-download-assets.py "data/raw/ChatGPT Data ..." \\
        --only-conv 69e77b68-23b8-83e9-bca7-924256fc8e67
"""

import argparse
import asyncio
import logging
from pathlib import Path

from src.extractors.chatgpt.asset_downloader import (
    run_asset_download,
    extract_canvases,
    extract_deep_research,
)


def main():
    parser = argparse.ArgumentParser(description="Download assets do ChatGPT")
    parser.add_argument("raw_dir", type=Path, help="Dir do raw com chatgpt_raw.json")
    parser.add_argument(
        "--only-conv",
        action="append",
        default=None,
        help="Limita a essas conv IDs (pode repetir). Pra teste.",
    )
    parser.add_argument("--artifacts-only", action="store_true",
                        help="So extrai Canvas + Deep Research, pula download de imagens")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")

    # Canvas + Deep Research (offline, le raw)
    print("=== Canvas / Deep Research (offline) ===")
    c = extract_canvases(args.raw_dir)
    print(f"Canvas: extracted={c['extracted']}, patches={c['updates_patch']}, "
          f"skip={c['skipped_existing']}, err={len(c['errors'])}")
    if c['by_type']:
        print(f"  by_type: {c['by_type']}")
    r = extract_deep_research(args.raw_dir)
    print(f"Deep Research: extracted={r['extracted']}, skip={r['skipped_existing']}, "
          f"err={len(r['errors'])}")

    if args.artifacts_only:
        return

    # Imagens via API (Playwright pra token)
    print("\n=== Imagens (via API) ===")
    report = asyncio.run(run_asset_download(
        args.raw_dir,
        only_conv_ids=args.only_conv,
    ))
    print("\n" + report.summary())


if __name__ == "__main__":
    main()
