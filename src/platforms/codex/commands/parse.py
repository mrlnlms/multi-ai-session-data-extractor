"""Parse data/raw/Codex/ → 7 parquets canonicos, incluindo assets de entrada."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.runtime.project import find_project_root

from src.capture.cli.copy import current_source_files
from src.platforms.codex.parser import CodexParser

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = find_project_root(Path(__file__))
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Codex"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "Codex"


def main() -> int:
    if not RAW_DIR.exists():
        logger.error(f"Raw nao existe: {RAW_DIR}")
        logger.error("Rode primeiro: python -m src.platforms.codex.commands.sync")
        return 1
    logger.info(f"Parsing {RAW_DIR}...")
    parser = CodexParser()
    home_files = current_source_files("codex")
    parser.parse(RAW_DIR, home_memory_files=home_files)
    stats = parser.write_parquets(PROCESSED_DIR)
    print()
    print("=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v:,}")
    print(f"\nParquets em: {PROCESSED_DIR}")
    return 0


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    sys.exit(main())
