"""Parser Grok: merged -> parquet canonico.

Uso:
    python scripts/grok-parse.py
"""

import argparse
from pathlib import Path

from src.parsers.grok import GrokParser


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default="data/merged/Grok", help="Merged dir")
    ap.add_argument("--out", default="data/processed/Grok", help="Output dir")
    ap.add_argument("--account", default=None)
    args = ap.parse_args()

    parser = GrokParser(account=args.account, merged_root=Path(args.merged))
    parser.parse(Path(args.merged))
    parser.save(Path(args.out))

    print(
        f"Conversations: {len(parser.conversations)} | "
        f"Messages: {len(parser.messages)} | "
        f"ToolEvents: {len(parser.events)} | "
        f"Workspaces: {len(parser.workspaces)} | "
        f"ConversationProjects: {len(parser.conversation_projects)}"
    )
    print(f"Output: {args.out}")


if __name__ == "__main__":
    main()
