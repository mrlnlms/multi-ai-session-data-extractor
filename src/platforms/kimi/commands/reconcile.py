"""Reconciler Kimi standalone.

Uso:
    PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.reconcile
    PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.reconcile --full
"""

import argparse
import sys
from pathlib import Path

from src.platforms.kimi.extractor.orchestrator import BASE_DIR as RAW_DIR
from src.platforms.kimi.reconciler import run_reconciliation


MERGED_DIR = Path("data/merged/Kimi")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw_dir", nargs="?", default=None)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--previous-merged", default=None)
    args = ap.parse_args()

    raw = Path(args.raw_dir) if args.raw_dir else RAW_DIR
    if not raw.exists() or not (raw / "discovery_ids.json").exists():
        print(f"ERRO: raw nao encontrado em {raw}. Rode python -m src.platforms.kimi.commands.export primeiro.")
        sys.exit(1)
    print(f"Raw: {raw}")

    prev = Path(args.previous_merged) if args.previous_merged else None
    r = run_reconciliation(raw, MERGED_DIR, prev, None, args.full)
    print("\n" + r.summary())
    if r.aborted:
        print(f"ABORTADO: {r.abort_reason}"); sys.exit(3)
    if r.warnings:
        print(f"\nWarnings ({len(r.warnings)}) primeiros 10:")
        for w in r.warnings[:10]: print(f"  {w}")
    print(f"\nMerged em: {MERGED_DIR}")


if __name__ == "__main__":
    main()
