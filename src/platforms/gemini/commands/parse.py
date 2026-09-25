"""Roda parser Gemini sobre todas as arvores data/merged/Gemini/account-N/.

Output em data/processed/Gemini/:
    gemini_conversations.parquet
    gemini_messages.parquet
    gemini_tool_events.parquet
    gemini_assets.parquet
    gemini_asset_links.parquet
    gemini_agent_memories.parquet
    gemini_agent_memory_versions.parquet
    gemini_agent_memory_temporal_evidence.parquet
"""

import argparse
import logging
from pathlib import Path

from src.accounts import account_presentation
from src.account_identity import resolve_account_id
from src.platforms.gemini.memory_parser import parse_account_instructions
from src.platforms.gemini.parser import GeminiParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/Gemini"))
    ap.add_argument("--raw-root", type=Path, default=Path("data/raw/Gemini"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/Gemini"))
    ap.add_argument("--accounts-file", type=Path, default=Path(".storage/accounts.json"))
    ap.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)
    log.info("Input merged: %s", args.merged_root)
    log.info("Output dir:   %s", args.output_dir)

    account_dirs = {
        path.name: path
        for root in (args.merged_root, args.raw_root)
        for path in root.glob("account-*") if path.is_dir()
    }
    account_ids = {
        name.removeprefix("account-"): resolve_account_id(
            "Gemini", name, args.catalog_path,
        ) for name in account_dirs
    }
    account_labels = {
        name: account_presentation(
            "Gemini", name, args.catalog_path,
            registry_source="gemini", registry_path=args.accounts_file,
        ) for name in account_dirs
    }
    parser = GeminiParser(
        merged_root=args.merged_root,
        account_labels=account_labels,
        account_ids=account_ids,
    )
    parser.parse(args.merged_root)
    for name in sorted(account_dirs):
        raw_tree = args.raw_root / name
        result = parse_account_instructions(
            raw_tree, account_ids[name.removeprefix("account-")]
        )
        parser.agent_memories.extend(result.memories)
        parser.agent_memory_versions.extend(result.versions)
        parser.agent_memory_temporal_evidence.extend(result.temporal_evidence)
    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
