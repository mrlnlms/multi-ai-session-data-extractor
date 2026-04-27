"""Reconcilia raw recem capturado com merged anterior.

Uso:
    python scripts/chatgpt-reconcile.py <raw_dir> [--previous-merged PATH]

Exemplo:
    python scripts/chatgpt-reconcile.py "data/raw/ChatGPT Data 2026-04-23/"
"""

import argparse
import logging
from pathlib import Path

from src.reconcilers.chatgpt import run_reconciliation


def main():
    parser = argparse.ArgumentParser(description="Reconcilia raw do ChatGPT com merged anterior")
    parser.add_argument("raw_dir", type=Path, help="Pasta do raw (contem chatgpt_raw.json)")
    parser.add_argument("--previous-merged", type=Path, default=None,
                       help="Override do merged anterior (default: auto-detect mais recente)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")

    merged_base = Path("data/merged/ChatGPT")
    report = run_reconciliation(args.raw_dir, merged_base, previous_merged=args.previous_merged)

    if report.aborted:
        print(f"ABORTED: {report.abort_reason}")
        exit(1)

    print(report.summary())


if __name__ == "__main__":
    main()
