"""Roda parser Gemini sobre todas as arvores data/merged/Gemini/account-N/.

Output em data/processed/Gemini/:
    gemini_conversations.parquet
    gemini_messages.parquet
    gemini_tool_events.parquet
    gemini_assets.parquet
    gemini_asset_links.parquet
"""

import argparse
import logging
from pathlib import Path

from src.accounts import account_presentation
from src.account_identity import resolve_account_id
from src.platforms.gemini.parser import GeminiParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/Gemini"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/Gemini"))
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)
    log.info("Input merged: %s", args.merged_root)
    log.info("Output dir:   %s", args.output_dir)

    account_dirs = [path for path in args.merged_root.glob("account-*") if path.is_dir()]
    account_ids = {
        account_dir.name.removeprefix("account-"): resolve_account_id(
            "Gemini", account_dir.name, args.catalog_path,
        ) for account_dir in account_dirs
    }
    account_labels = {
        account_dir.name: account_presentation(
            "Gemini", account_dir.name, args.catalog_path,
            registry_source="gemini", registry_path=args.accounts_file,
        ) for account_dir in account_dirs
    }
    parser = GeminiParser(
        merged_root=args.merged_root,
        account_labels=account_labels,
        account_ids=account_ids,
    )
    parser.parse(args.merged_root)
    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
