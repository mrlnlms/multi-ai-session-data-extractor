"""Roda parser Gemini sobre data/merged/Gemini/account-{1,2}/.

Output em data/processed/Gemini/:
    gemini_conversations.parquet
    gemini_messages.parquet
    gemini_tool_events.parquet
"""

import argparse
import logging
from pathlib import Path

from src.accounts import load_account_registry
from src.platforms.gemini.parser import GeminiParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/Gemini"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/Gemini"))
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)
    log.info("Input merged: %s", args.merged_root)
    log.info("Output dir:   %s", args.output_dir)

    account_labels = load_account_registry(args.accounts_file).get("gemini", {})
    parser = GeminiParser(merged_root=args.merged_root, account_labels=account_labels)
    parser.parse(args.merged_root)
    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
