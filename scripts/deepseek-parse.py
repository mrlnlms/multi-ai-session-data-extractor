"""Roda parser DeepSeek sobre data/merged/DeepSeek/."""

import argparse
import logging
from pathlib import Path

from src.parsers.deepseek import DeepSeekParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged-root", type=Path, default=Path("data/merged/DeepSeek"))
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed/DeepSeek"))
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

    parser = DeepSeekParser(account=args.account, merged_root=args.merged_root)
    parser.parse(args.merged_root)

    log.info(
        f"Parseado: {len(parser.conversations)} convs, "
        f"{len(parser.messages)} msgs, "
        f"{len(parser.events)} tool_events, "
        f"{len(parser.branches)} branches"
    )

    parser.save(args.output_dir)
    log.info("Parquets gravados.")


if __name__ == "__main__":
    main()
