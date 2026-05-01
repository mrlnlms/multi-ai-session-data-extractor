"""Roda parser Qwen sobre data/merged/Qwen/.

Output em data/processed/Qwen/:
    qwen_conversations.parquet
    qwen_messages.parquet
    qwen_tool_events.parquet
    qwen_branches.parquet
    qwen_project_metadata.parquet
    qwen_project_docs.parquet
"""

import argparse
import logging
from pathlib import Path

from src.parsers.qwen import QwenParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/Qwen"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/Qwen"))
    ap.add_argument("--account", default=None)
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

    parser = QwenParser(account=args.account, merged_root=args.merged_root)
    parser.parse(args.merged_root)

    log.info(
        f"Parseado: {len(parser.conversations)} convs, "
        f"{len(parser.messages)} msgs, "
        f"{len(parser.events)} tool_events, "
        f"{len(parser.branches)} branches, "
        f"{len(parser.projects)} projects, "
        f"{len(parser.project_docs)} project docs"
    )

    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
