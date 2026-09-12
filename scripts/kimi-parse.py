"""Parser Kimi: merged -> parquet canonico.

Uso:
    python scripts/kimi-parse.py
"""

import argparse
from pathlib import Path

from src.accounts import account_email
from src.parsers.kimi import KimiParser


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default="data/merged/Kimi")
    ap.add_argument("--out", default="data/processed/Kimi")
    ap.add_argument("--account", default=None)
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    args = ap.parse_args()

    merged_root = Path(args.merged)
    account_trees = [("default", merged_root)]
    for account_dir in sorted(merged_root.glob("account-*")):
        if account_dir.is_dir():
            account_trees.append((account_dir.name, account_dir))

    parser = KimiParser(merged_root=merged_root)
    parser.reset()
    for profile, tree in account_trees:
        account = args.account or account_email("kimi", profile, args.accounts_file)
        per_account = KimiParser(account=account, merged_root=tree)
        per_account.parse(tree)
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.events.extend(per_account.events)
        parser.branches.extend(per_account.branches)
        parser.skills["official"].extend(per_account.skills.get("official") or [])
        parser.skills["installed"].extend(per_account.skills.get("installed") or [])
        parser.assets_manifest.update(per_account.assets_manifest)
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
