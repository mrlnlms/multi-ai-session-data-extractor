"""Parse data/raw/Antigravity CLI/ → 4 parquets canonicos."""

from __future__ import annotations

import sys
from pathlib import Path

from src.runtime.project import find_project_root

from src.parsers.antigravity_cli import AntigravityCLIParser


PROJECT_ROOT = find_project_root(Path(__file__))
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Antigravity CLI"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "Antigravity CLI"


def main() -> int:
    if not RAW_DIR.exists():
        print(f"Raw nao existe: {RAW_DIR}", file=sys.stderr)
        return 1
    parser = AntigravityCLIParser()
    parser.parse(RAW_DIR)
    stats = parser.write_parquets(PROCESSED_DIR)
    for key, value in stats.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
