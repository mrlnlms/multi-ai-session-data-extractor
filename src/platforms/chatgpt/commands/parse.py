"""Roda o parser ChatGPT sobre todas as arvores merged de conta.

Output em data/processed/ChatGPT/: conversations, messages, tool_events,
branches, assets, asset_links and the three versioned agent-memory tables.

Uso:
    PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.parse
    PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.parse --merged-path <path> --output-dir <dir>
"""

import argparse
import logging
from pathlib import Path

from src.accounts import account_presentation, uses_legacy_account_layout
from src.account_identity import resolve_account_id
from src.platforms.chatgpt.parser import ChatGPTParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--merged-path", type=Path, default=Path("data/merged/ChatGPT/chatgpt_merged.json"),
        help="Path pro merged (default: data/merged/ChatGPT/chatgpt_merged.json)",
    )
    ap.add_argument(
        "--raw-root", type=Path, default=Path("data/raw/ChatGPT"),
        help="Root dos raws (assets e historico de memorias/instrucoes por conta)",
    )
    ap.add_argument(
        "--output-dir", type=Path, default=Path("data/processed/ChatGPT"),
        help="Output dir (default: data/processed/ChatGPT)",
    )
    ap.add_argument("--account", default=None, help="Override the configured account e-mail")
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)

    log.info(f"Input merged: {args.merged_path}")
    log.info(f"Raw root (assets): {args.raw_root}")
    log.info(f"Output dir: {args.output_dir}")

    account_trees = []
    if uses_legacy_account_layout(args.catalog_path):
        account_trees.append(("default", args.merged_path, args.raw_root))
    merged_base = args.merged_path.parent
    for account_dir in sorted(merged_base.glob("account-*")):
        merged = account_dir / "chatgpt_merged.json"
        if merged.is_file():
            # Catalog identity resolves UUID directories and legacy aliases;
            # a directory name does not imply a local browser profile binding.
            key = account_dir.name
            account_trees.append((key, merged, args.raw_root / account_dir.name))
    known = {key for key, _, _ in account_trees}
    for raw_dir in sorted(args.raw_root.glob("account-*")):
        if raw_dir.is_dir() and raw_dir.name not in known and (
            (raw_dir / "_account_memory").is_dir()
            or (raw_dir / "_project_settings").is_dir()
            or (raw_dir / "chatgpt_memories.json").is_file()
            or (raw_dir / "chatgpt_instructions.json").is_file()
            or (raw_dir / "chatgpt_memory_summary.json").is_file()
            or (raw_dir / "chatgpt_memories.md").is_file()
        ):
            account_trees.append((raw_dir.name, None, raw_dir))
    if not account_trees:
        raise FileNotFoundError(
            f"Nenhuma arvore merged encontrada em {merged_base}"
        )

    parser = ChatGPTParser(raw_root=args.raw_root)
    parser.reset()
    for profile, merged, raw_root in account_trees:
        account = args.account or account_presentation(
            "ChatGPT", profile, args.catalog_path,
            registry_source="chatgpt", registry_path=args.accounts_file,
        )
        account_id = resolve_account_id("ChatGPT", profile, args.catalog_path)
        per_account = ChatGPTParser(account=account, account_id=account_id, raw_root=raw_root)
        if merged is not None:
            per_account.parse(merged)
        else:
            per_account.parse_account_memory()
        parser.conversations.extend(per_account.conversations)
        parser.messages.extend(per_account.messages)
        parser.events.extend(per_account.events)
        parser.branches.extend(per_account.branches)
        parser.assets.extend(per_account.assets)
        parser.asset_links.extend(per_account.asset_links)
        parser.agent_memories.extend(per_account.agent_memories)
        parser.agent_memory_versions.extend(per_account.agent_memory_versions)
        parser.agent_memory_temporal_evidence.extend(per_account.agent_memory_temporal_evidence)

    log.info(
        f"Parseado: {len(parser.conversations)} convs, "
        f"{len(parser.messages)} msgs, {len(parser.events)} tool_events, "
        f"{len(parser.assets)} assets, {len(parser.asset_links)} asset_links, "
        f"{len(parser.agent_memories)} memory documents, {len(parser.agent_memory_versions)} memory versions"
    )

    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
