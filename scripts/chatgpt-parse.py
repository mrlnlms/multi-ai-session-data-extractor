"""Roda o parser ChatGPT sobre todas as arvores merged de conta.

Output em data/processed/ChatGPT/{conversations,messages,tool_events,branches}.parquet.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py
    PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py --merged-path <path> --output-dir <dir>
"""

import argparse
import logging
from pathlib import Path

from src.accounts import account_email
from src.parsers.chatgpt import ChatGPTParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--merged-path", type=Path, default=Path("data/merged/ChatGPT/chatgpt_merged.json"),
        help="Path pro merged (default: data/merged/ChatGPT/chatgpt_merged.json)",
    )
    ap.add_argument(
        "--raw-root", type=Path, default=Path("data/raw/ChatGPT"),
        help="Root dos raws (pra resolver asset_paths via data/raw/ChatGPT/assets/)",
    )
    ap.add_argument(
        "--output-dir", type=Path, default=Path("data/processed/ChatGPT"),
        help="Output dir (default: data/processed/ChatGPT)",
    )
    ap.add_argument("--account", default=None, help="Override the configured account e-mail")
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)

    if not args.merged_path.is_file():
        raise FileNotFoundError(f"Merged nao encontrado: {args.merged_path}")

    log.info(f"Input merged: {args.merged_path}")
    log.info(f"Raw root (assets): {args.raw_root}")
    log.info(f"Output dir: {args.output_dir}")

    account_trees = [("default", args.merged_path, args.raw_root)]
    merged_base = args.merged_path.parent
    for account_dir in sorted(merged_base.glob("account-*")):
        merged = account_dir / "chatgpt_merged.json"
        if merged.is_file():
            # The directory name is also the technical profile key used by
            # chatgpt-login/sync and by .storage/accounts.json.
            key = account_dir.name
            account_trees.append((key, merged, args.raw_root / account_dir.name))

    parser = ChatGPTParser(raw_root=args.raw_root)
    parser.reset()
    for profile, merged, raw_root in account_trees:
        account = args.account or account_email("chatgpt", profile, args.accounts_file)
        per_account = ChatGPTParser(account=account, raw_root=raw_root)
        per_account.parse(merged)
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.events.extend(per_account.events)
        parser.branches.extend(per_account.branches)

    log.info(
        f"Parseado: {len(parser.conversations)} convs, "
        f"{len(parser.messages)} msgs, {len(parser.events)} tool_events"
    )

    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
