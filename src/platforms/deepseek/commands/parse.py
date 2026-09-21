"""Roda parser DeepSeek sobre data/merged/DeepSeek/."""

import argparse
import logging
from pathlib import Path

from src.accounts import account_presentation, uses_legacy_account_layout
from src.account_identity import resolve_account_id
from src.platforms.deepseek.parser import DeepSeekParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/DeepSeek"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/DeepSeek"))
    ap.add_argument("--account", default=None)
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
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

    account_trees = [("default", args.merged_root)] if uses_legacy_account_layout(args.catalog_path) else []
    for account_dir in sorted(args.merged_root.glob("account-*")):
        if account_dir.is_dir():
            account_trees.append((account_dir.name, account_dir))

    parser = DeepSeekParser(merged_root=args.merged_root)
    parser.reset()
    for profile, tree in account_trees:
        account = args.account or account_presentation(
            "DeepSeek", profile, args.catalog_path,
            registry_source="deepseek", registry_path=args.accounts_file,
        )
        account_id = resolve_account_id("DeepSeek", profile, args.catalog_path)
        per_account = DeepSeekParser(account=account, account_id=account_id, merged_root=tree)
        per_account.parse(tree)
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.events.extend(per_account.events)
        parser.branches.extend(per_account.branches)
        parser.assets.extend(per_account.assets)
        parser.asset_links.extend(per_account.asset_links)

    log.info(
        f"Parseado: {len(parser.conversations)} convs, "
        f"{len(parser.messages)} msgs, "
        f"{len(parser.events)} tool_events, "
        f"{len(parser.branches)} branches, "
        f"{len(parser.assets)} assets, "
        f"{len(parser.asset_links)} asset_links"
    )

    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
