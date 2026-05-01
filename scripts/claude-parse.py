"""Roda o parser Claude.ai sobre data/merged/Claude.ai/.

Output em data/processed/Claude.ai/:
    claude_ai_conversations.parquet
    claude_ai_messages.parquet
    claude_ai_tool_events.parquet
    claude_ai_branches.parquet
    claude_ai_project_metadata.parquet (auxiliar — counts por project)

Uso:
    PYTHONPATH=. .venv/bin/python scripts/claude-parse.py
    PYTHONPATH=. .venv/bin/python scripts/claude-parse.py --merged-root <path> --output-dir <dir>
"""

import argparse
import logging
from pathlib import Path

from src.parsers.claude_ai import ClaudeAIParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--merged-root", type=Path, default=Path("data/merged/Claude.ai"),
        help="Pasta merged (default: data/merged/Claude.ai)",
    )
    ap.add_argument(
        "--output-dir", type=Path, default=Path("data/processed/Claude.ai"),
        help="Output dir (default: data/processed/Claude.ai)",
    )
    ap.add_argument(
        "--account", default=None,
        help="Tag account no campo Conversation.account (default: None)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)

    if not args.merged_root.is_dir():
        raise FileNotFoundError(f"Merged dir nao encontrado: {args.merged_root}")

    log.info(f"Input merged: {args.merged_root}")
    log.info(f"Output dir:   {args.output_dir}")

    parser = ClaudeAIParser(account=args.account, merged_root=args.merged_root)
    parser.parse(args.merged_root)

    log.info(
        f"Parseado: {len(parser.conversations)} convs, "
        f"{len(parser.messages)} msgs, "
        f"{len(parser.events)} tool_events, "
        f"{len(parser.branches)} branches, "
        f"{len(parser.projects)} projects"
    )

    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
