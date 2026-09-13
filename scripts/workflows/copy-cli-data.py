"""Wrapper CLI pra `src.extractors.cli.copy.copy_source`.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/workflows/copy-cli-data.py            # todas as 4 CLIs
    PYTHONPATH=. .venv/bin/python scripts/workflows/copy-cli-data.py --source claude_code
    PYTHONPATH=. .venv/bin/python scripts/workflows/copy-cli-data.py --no-snapshot
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.extractors.cli.copy import SOURCES, copy_source
from src.extractors.cli.snapshot import snapshot_configs

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=list(SOURCES.keys()), default=None,
                    help="Roda so 1 source (default: todas as 4 CLIs)")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="Skip snapshot blob (debug/test)")
    args = ap.parse_args()

    sources = [args.source] if args.source else list(SOURCES.keys())

    logger.info("Copiando dados CLI pra data/raw/ (incremental)...")
    for s in sources:
        copy_source(s)

    if not args.no_snapshot:
        logger.info("Snapshot dos configs/skills/hooks → data/external/...")
        snapshot_configs()

    logger.info("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
