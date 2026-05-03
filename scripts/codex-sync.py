"""Sync Codex — copy + parse + log em 1 comando."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.cli.copy import copy_source as _copy_source
from src.parsers.codex import CodexParser

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Codex"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "Codex"


def main() -> int:
    started_at = datetime.now(timezone.utc)

    print("=" * 60)
    print("  Etapa 1/2 — Copy ~/.codex/sessions/ → data/raw/Codex/")
    print("=" * 60)
    copy_result = _copy_source("codex")
    n_new = len(copy_result["new"])
    n_upd = len(copy_result["updated"])

    print()
    print("=" * 60)
    print("  Etapa 2/2 — Parse → data/processed/Codex/")
    print("=" * 60)
    parser = CodexParser()
    parser.parse(RAW_DIR)
    stats = parser.write_parquets(PROCESSED_DIR)

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    log_entry = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": duration,
        "totals": {
            "files_new": n_new,
            "files_updated": n_upd,
            "conversations": stats["conversations"],
            "messages": stats["messages"],
            "tool_events": stats["tool_events"],
            "branches": stats["branches"],
        },
    }
    log_path = RAW_DIR / "capture_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    print()
    print("=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v:,}")
    print(f"  duration: {duration:.1f}s, files: {n_new} new + {n_upd} updated")
    print(f"\nParquets em: {PROCESSED_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
