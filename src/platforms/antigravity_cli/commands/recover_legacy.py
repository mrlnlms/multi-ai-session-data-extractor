#!/usr/bin/env python3
"""Recover readable trajectories from legacy Antigravity CLI PB containers."""

from pathlib import Path

from src.platforms.antigravity_cli.legacy_recovery import main
from src.runtime.project import find_project_root


if __name__ == "__main__":
    raise SystemExit(main(find_project_root(Path(__file__))))
