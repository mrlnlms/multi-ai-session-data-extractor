"""Reconciler Qwen standalone (pasta unica).

Uso:
    python scripts/qwen-reconcile.py            # raw=data/raw/Qwen/
    python scripts/qwen-reconcile.py --full
"""

import argparse
import sys
from pathlib import Path

from src.extractors.qwen.orchestrator import BASE_DIR as RAW_DIR
from src.reconcilers.qwen import run_reconciliation, FEATURE_FLAGS


MERGED_DIR = Path("data/merged/Qwen")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw_dir", nargs="?", default=None, help=f"Raw dir (default: {RAW_DIR})")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--refetch-features", default=None)
    ap.add_argument("--previous-merged", default=None)
    args = ap.parse_args()

    raw = Path(args.raw_dir) if args.raw_dir else RAW_DIR
    if not raw.exists() or not (raw / "discovery_ids.json").exists():
        print(f"ERRO: raw nao encontrado em {raw}. Rode scripts/qwen-export.py primeiro.")
        sys.exit(1)
    print(f"Raw: {raw}")

    prev = Path(args.previous_merged) if args.previous_merged else None
    force_feats = None
    if args.refetch_features:
        feats = {f.strip() for f in args.refetch_features.split(",") if f.strip()}
        invalid = feats - FEATURE_FLAGS
        if invalid:
            print(f"ERRO: features invalidas: {invalid}; disponiveis: {sorted(FEATURE_FLAGS)}")
            sys.exit(2)
        force_feats = feats

    r = run_reconciliation(raw, MERGED_DIR, prev, force_feats, args.full)
    print("\n" + r.summary())
    if r.aborted:
        print(f"ABORTADO: {r.abort_reason}"); sys.exit(3)
    if r.warnings:
        print(f"\nWarnings ({len(r.warnings)}) primeiros 10:")
        for w in r.warnings[:10]: print(f"  {w}")
    print(f"\nMerged em: {MERGED_DIR}")


if __name__ == "__main__":
    main()
