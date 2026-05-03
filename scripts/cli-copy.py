"""Wrapper CLI pra `src.extractors.cli.copy.copy_source`.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/cli-copy.py            # todos os 3
    PYTHONPATH=. .venv/bin/python scripts/cli-copy.py --source claude_code
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.extractors.cli.copy import SOURCES, copy_source

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=list(SOURCES.keys()), default=None,
                    help="Roda so 1 source (default: todos os 3)")
    args = ap.parse_args()

    sources = [args.source] if args.source else list(SOURCES.keys())

    logger.info("Copiando dados CLI pra data/raw/ (incremental)...")
    for s in sources:
        copy_source(s)
    logger.info("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
