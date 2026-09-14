"""Parser Kimi: merged -> parquet canonico.

Uso:
    PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.parse
"""

import argparse
from pathlib import Path

from src.accounts import account_email
from src.account_identity import resolve_account_id, stamp_account_id_rows
from src.platforms.kimi.parser import KimiParser


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default="data/merged/Kimi")
    ap.add_argument("--out", default="data/processed/Kimi")
    ap.add_argument("--account", default=None)
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
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
        account_id = resolve_account_id("Kimi", profile, args.catalog_path)
        per_account = KimiParser(account=account, account_id=account_id, merged_root=tree)
        per_account.parse(tree)
        for rows in per_account.skills.values():
            stamp_account_id_rows(rows, account_id)
        for row in per_account.assets_manifest.values():
            if isinstance(row, dict):
                row["account_id"] = account_id
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
