"""Parse data/raw/Claude Code/ → 5 parquets canonicos.

Le todos JSONLs em data/raw/Claude Code/<encoded-cwd>/*.jsonl + subagents
e gera 5 parquets em data/processed/Claude Code/:
- claude_code_conversations.parquet
- claude_code_messages.parquet
- claude_code_tool_events.parquet
- claude_code_branches.parquet
- claude_code_agent_memories.parquet

Idempotente — rodar 2x = mesmos bytes.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/claude-code-parse.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.extractors.cli.copy import current_source_files
from src.parsers.claude_code import ClaudeCodeParser

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Claude Code"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "Claude Code"


def main() -> int:
    if not RAW_DIR.exists():
        logger.error(f"Raw nao existe: {RAW_DIR}")
        logger.error("Rode primeiro: scripts/cli-copy.py --source claude_code")
        return 1

    logger.info(f"Parsing {RAW_DIR}...")
    parser = ClaudeCodeParser()
    home_files = current_source_files("claude_code")
    parser.parse(RAW_DIR, home_memory_files=home_files)
    stats = parser.write_parquets(PROCESSED_DIR)

    print()
    print("=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v:,}")
    print(f"\nParquets em: {PROCESSED_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
