"""Parser canonico Perplexity v3 — merged -> 4 parquets.

Le data/merged/Perplexity/ e escreve data/processed/Perplexity/{
  conversations, messages, tool_events, branches}.parquet.

Idempotente: rodar 2x produz mesmos bytes.
Uso: python scripts/perplexity-parse.py
"""

import argparse
from pathlib import Path

from src.accounts import account_email
from src.parsers.perplexity import PerplexityParser


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/Perplexity"))
    ap.add_argument("--raw-root", type=Path, default=Path("data/raw/Perplexity"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/Perplexity"))
    ap.add_argument("--account", default=None, help="Override the configured account e-mail")
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    args = ap.parse_args()
    account_trees = [("default", args.merged_root, args.raw_root)]
    for account_dir in sorted(args.merged_root.glob("account-*")):
        if account_dir.is_dir():
            account_trees.append((account_dir.name, account_dir, args.raw_root / account_dir.name))

    parser = PerplexityParser(merged_root=args.merged_root, raw_root=args.raw_root)
    parser.reset()
    for profile, merged_tree, raw_tree in account_trees:
        account = args.account or account_email("perplexity", profile, args.accounts_file)
        per_account = PerplexityParser(
            account=account, merged_root=merged_tree, raw_root=raw_tree,
        )
        per_account.parse()
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.tool_events.extend(per_account.tool_events)
        parser.branches.extend(per_account.branches)
    stats = parser.save(args.output_dir)
    print("=== Perplexity parse done ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
