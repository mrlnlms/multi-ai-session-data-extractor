"""Parser canonico Perplexity v3 — merged -> canonical and asset parquets.

Le data/merged/Perplexity/ e escreve data/processed/Perplexity/{
  conversations, messages, tool_events, branches, assets, asset_links}.parquet.

Idempotente: rodar 2x produz mesmos bytes.
Uso: PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.parse
"""

import argparse
from pathlib import Path

from src.accounts import account_presentation, uses_legacy_account_layout
from src.account_identity import resolve_account_id
from src.platforms.perplexity.parser import PerplexityParser
from src.platforms.perplexity.memory_parser import parse_account_memory


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/Perplexity"))
    ap.add_argument("--raw-root", type=Path, default=Path("data/raw/Perplexity"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/Perplexity"))
    ap.add_argument("--account", default=None, help="Override the configured account e-mail")
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
    args = ap.parse_args()
    account_trees = ([("default", args.merged_root, args.raw_root)]
                     if uses_legacy_account_layout(args.catalog_path) else [])
    for account_dir in sorted(args.merged_root.glob("account-*")):
        if account_dir.is_dir():
            account_trees.append((account_dir.name, account_dir, args.raw_root / account_dir.name))
    known_accounts = {key for key, _, _ in account_trees}
    for raw_dir in sorted(args.raw_root.glob("account-*")):
        if (raw_dir.is_dir() and raw_dir.name not in known_accounts
                and (raw_dir / "_account_memory").is_dir()):
            account_trees.append((raw_dir.name, None, raw_dir))

    parser = PerplexityParser(merged_root=args.merged_root, raw_root=args.raw_root)
    parser.reset()
    for profile, merged_tree, raw_tree in account_trees:
        account = args.account or account_presentation(
            "Perplexity", profile, args.catalog_path,
            registry_source="perplexity", registry_path=args.accounts_file,
        )
        account_id = resolve_account_id("Perplexity", profile, args.catalog_path)
        per_account = PerplexityParser(
            account=account, account_id=account_id,
            merged_root=merged_tree, raw_root=raw_tree,
        )
        if merged_tree is not None:
            per_account.parse()
        memory_result = parse_account_memory(raw_tree, account_id)
        per_account.agent_memories.extend(memory_result.memories)
        per_account.agent_memory_versions.extend(memory_result.versions)
        per_account.agent_memory_temporal_evidence.extend(memory_result.temporal_evidence)
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.tool_events.extend(per_account.tool_events)
        parser.branches.extend(per_account.branches)
        parser.assets.extend(per_account.assets)
        parser.asset_links.extend(per_account.asset_links)
        parser.agent_memories.extend(per_account.agent_memories)
        parser.agent_memory_versions.extend(per_account.agent_memory_versions)
        parser.agent_memory_temporal_evidence.extend(per_account.agent_memory_temporal_evidence)
    stats = parser.save(args.output_dir)
    print("=== Perplexity parse done ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
