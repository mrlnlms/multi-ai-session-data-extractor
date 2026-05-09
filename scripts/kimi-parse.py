"""Parser Kimi: merged -> parquet canonico.

Uso:
    python scripts/kimi-parse.py
"""

import argparse
from pathlib import Path

from src.parsers.kimi import KimiParser


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default="data/merged/Kimi")
    ap.add_argument("--out", default="data/processed/Kimi")
    ap.add_argument("--account", default=None)
    args = ap.parse_args()

    parser = KimiParser(account=args.account, merged_root=Path(args.merged))
    parser.parse(Path(args.merged))
    parser.save(Path(args.out))

    print(
        f"Conversations: {len(parser.conversations)} | "
        f"Messages: {len(parser.messages)} | "
        f"ToolEvents: {len(parser.events)} | "
        f"Branches: {len(parser.branches)} | "
        f"Skills (installed): {len(parser.skills.get('installed') or [])} | "
        f"Assets: {len(parser.assets_manifest)}"
    )
    print(f"Output: {args.out}")


if __name__ == "__main__":
    main()
