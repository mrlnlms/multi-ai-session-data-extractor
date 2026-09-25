"""Roda o parser Claude.ai sobre data/merged/Claude.ai/.

Output em data/processed/Claude.ai/:
    claude_ai_conversations.parquet
    claude_ai_messages.parquet
    claude_ai_tool_events.parquet
    claude_ai_branches.parquet
    claude_ai_project_metadata.parquet (auxiliar — counts por project)
    claude_ai_project_docs.parquet
    claude_ai_assets.parquet
    claude_ai_asset_links.parquet
    claude_ai_agent_memories.parquet
    claude_ai_agent_memory_versions.parquet
    claude_ai_agent_memory_temporal_evidence.parquet

Uso:
    PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.parse
    PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.parse --merged-root <path> --output-dir <dir>
"""

import argparse
import logging
from pathlib import Path

from src.accounts import account_presentation, uses_legacy_account_layout
from src.account_identity import resolve_account_id, stamp_account_id_rows
from src.platforms.claude_ai.parser import ClaudeAIParser
from src.platforms.claude_ai.memory_parser import parse_account_memory


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--merged-root", type=Path, default=Path("data/merged/Claude.ai"),
        help="Pasta merged (default: data/merged/Claude.ai)",
    )
    ap.add_argument(
        "--raw-root", type=Path, default=Path("data/raw/Claude.ai"),
        help="Pasta raw com historico de memorias por conta",
    )
    ap.add_argument(
        "--output-dir", type=Path, default=Path("data/processed/Claude.ai"),
        help="Output dir (default: data/processed/Claude.ai)",
    )
    ap.add_argument(
        "--account", default=None,
        help="Tag account no campo Conversation.account (default: None)",
    )
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
    known_accounts = {key for key, _ in account_trees}
    for raw_dir in sorted(args.raw_root.glob("account-*")):
        if raw_dir.is_dir() and raw_dir.name not in known_accounts and (
            (raw_dir / "_account_memory").is_dir() or (raw_dir / "claude_ai_memory.md").is_file()
        ):
            account_trees.append((raw_dir.name, None))

    parser = ClaudeAIParser(merged_root=args.merged_root)
    parser.reset()
    for profile, merged_root in account_trees:
        account = args.account or account_presentation(
            "Claude.ai", profile, args.catalog_path,
            registry_source="claude_ai", registry_path=args.accounts_file,
        )
        account_id = resolve_account_id("Claude.ai", profile, args.catalog_path)
        per_account = ClaudeAIParser(
            account=account, account_id=account_id, merged_root=merged_root,
        )
        if merged_root is not None:
            per_account.parse(merged_root)
        memory_result = parse_account_memory(args.raw_root / profile, account_id)
        per_account.agent_memories.extend(memory_result.memories)
        per_account.agent_memory_versions.extend(memory_result.versions)
        per_account.agent_memory_temporal_evidence.extend(memory_result.temporal_evidence)
        stamp_account_id_rows(per_account.projects, account_id)
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.events.extend(per_account.events)
        parser.branches.extend(per_account.branches)
        parser.projects.extend(per_account.projects)
        parser.project_docs.extend(per_account.project_docs)
        parser.assets.extend(per_account.assets)
        parser.asset_links.extend(per_account.asset_links)
        parser.agent_memories.extend(per_account.agent_memories)
        parser.agent_memory_versions.extend(per_account.agent_memory_versions)
        parser.agent_memory_temporal_evidence.extend(per_account.agent_memory_temporal_evidence)

    log.info(
        f"Parseado: {len(parser.conversations)} convs, "
        f"{len(parser.messages)} msgs, "
        f"{len(parser.events)} tool_events, "
        f"{len(parser.branches)} branches, "
        f"{len(parser.projects)} projects, "
        f"{len(parser.project_docs)} project docs, "
        f"{len(parser.assets)} assets, {len(parser.asset_links)} asset links, "
        f"{len(parser.agent_memories)} memory documents"
    )

    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
