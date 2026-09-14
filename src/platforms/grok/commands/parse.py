"""Parser Grok: merged -> parquet canonico.

Uso:
    PYTHONPATH=. .venv/bin/python -m src.platforms.grok.commands.parse
"""

import argparse
from pathlib import Path

from src.accounts import account_email
from src.account_identity import resolve_account_id, stamp_account_id_rows
from src.platforms.grok.parser import GrokParser


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default="data/merged/Grok", help="Merged dir")
    ap.add_argument("--out", default="data/processed/Grok", help="Output dir")
    ap.add_argument("--account", default=None)
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
    args = ap.parse_args()

    merged_root = Path(args.merged)
    account_trees = [("default", merged_root)]
    for account_dir in sorted(merged_root.glob("account-*")):
        if account_dir.is_dir():
            account_trees.append((account_dir.name, account_dir))

    parser = GrokParser(merged_root=merged_root)
    parser.reset()
    for profile, tree in account_trees:
        account = args.account or account_email("grok", profile, args.accounts_file)
        account_id = resolve_account_id("Grok", profile, args.catalog_path)
        per_account = GrokParser(account=account, account_id=account_id, merged_root=tree)
        per_account.parse(tree)
        stamp_account_id_rows(per_account.workspaces, account_id)
        stamp_account_id_rows(per_account.assets, account_id)
        for status in ("active", "inactive"):
            stamp_account_id_rows(per_account.scheduled_tasks.get(status) or [], account_id)
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.events.extend(per_account.events)
        parser.workspaces.extend(per_account.workspaces)
        parser.assets.extend(per_account.assets)
        parser.conversation_projects.extend(per_account.conversation_projects)
        for status in ("active", "inactive"):
            parser.scheduled_tasks.setdefault(status, []).extend(
                (per_account.scheduled_tasks.get(status) or [])
            )
        parser.asset_path_overrides.update({
            str(row["asset_id"]): str(row["asset_path"])
            for _, row in per_account.assets_df().iterrows()
            if row.get("asset_id") and row.get("asset_path")
        })
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
