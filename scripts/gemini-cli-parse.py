"""Parse data/raw/Gemini CLI/ → 4 parquets canonicos."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.parsers.gemini_cli import GeminiCLIParser

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Gemini CLI"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "Gemini CLI"


def main() -> int:
    if not RAW_DIR.exists():
        logger.error(f"Raw nao existe: {RAW_DIR}")
        logger.error("Rode primeiro: scripts/cli-copy.py --source gemini_cli")
        return 1
    logger.info(f"Parsing {RAW_DIR}...")
    parser = GeminiCLIParser()
    parser.parse(RAW_DIR)
    stats = parser.write_parquets(PROCESSED_DIR)
    print()
    print("=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v:,}")
    print(f"\nParquets em: {PROCESSED_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
