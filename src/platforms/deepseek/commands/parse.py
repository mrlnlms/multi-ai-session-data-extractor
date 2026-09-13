"""Roda parser DeepSeek sobre data/merged/DeepSeek/."""

import argparse
import logging
from pathlib import Path

from src.accounts import account_email
from src.platforms.deepseek.parser import DeepSeekParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/DeepSeek"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/DeepSeek"))
    ap.add_argument("--account", default=None)
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
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

    account_trees = [("default", args.merged_root)]
    for account_dir in sorted(args.merged_root.glob("account-*")):
        if account_dir.is_dir():
            account_trees.append((account_dir.name, account_dir))

    parser = DeepSeekParser(merged_root=args.merged_root)
    parser.reset()
    for profile, tree in account_trees:
        account = args.account or account_email("deepseek", profile, args.accounts_file)
        per_account = DeepSeekParser(account=account, merged_root=tree)
        per_account.parse(tree)
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.events.extend(per_account.events)
        parser.branches.extend(per_account.branches)

    log.info(
        f"Parseado: {len(parser.conversations)} convs, "
        f"{len(parser.messages)} msgs, "
        f"{len(parser.events)} tool_events, "
        f"{len(parser.branches)} branches"
    )

    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
