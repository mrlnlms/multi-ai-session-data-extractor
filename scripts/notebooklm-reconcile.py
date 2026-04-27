"""Reconciler NotebookLM — merge raw atual com merged anterior.

Uso:
    python scripts/notebooklm-reconcile.py --account hello [raw_dir]
    python scripts/notebooklm-reconcile.py --account hello --full
    python scripts/notebooklm-reconcile.py --account hello --refetch-features rLM1Ne_metadata

Default: auto-detecta raw mais recente do account + merged anterior.
"""

import argparse
import sys
from pathlib import Path

from src.extractors.notebooklm.auth import VALID_ACCOUNTS
from src.extractors.notebooklm.orchestrator import ACCOUNT_DIR_MAP
from src.reconcilers.notebooklm import run_reconciliation, FEATURE_FLAGS


def _find_latest_raw(account: str) -> Path | None:
    base = Path("data/raw/NotebookLM Data") / ACCOUNT_DIR_MAP[account]
    if not base.exists():
        return None
    cands = sorted(
        [p for p in base.iterdir() if p.is_dir() and len(p.name) == 16 and "T" in p.name],
        key=lambda p: p.stat().st_mtime,
    )
    return cands[-1] if cands else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=list(VALID_ACCOUNTS))
    parser.add_argument("raw_dir", nargs="?", default=None)
    parser.add_argument("--full", action="store_true",
                        help="Forca to_use em tudo (refetch completo)")
    parser.add_argument("--refetch-features", default=None,
                        help=f"Lista csv de features a forcar refetch (disponiveis: {','.join(sorted(FEATURE_FLAGS))})")
    parser.add_argument("--previous-merged", default=None,
                        help="Override do merged anterior (default: auto-detect)")
    args = parser.parse_args()

    if args.raw_dir:
        raw = Path(args.raw_dir)
    else:
        raw = _find_latest_raw(args.account)
        if not raw:
            print(f"ERRO: nenhum raw em data/raw/NotebookLM Data/{ACCOUNT_DIR_MAP[args.account]}/")
            sys.exit(1)
        print(f"Raw: {raw}")

    merged_base = Path("data/merged/NotebookLM") / ACCOUNT_DIR_MAP[args.account]
    prev_merged = Path(args.previous_merged) if args.previous_merged else None

    force_feats = None
    if args.refetch_features:
        feats = {f.strip() for f in args.refetch_features.split(",") if f.strip()}
        invalid = feats - FEATURE_FLAGS
        if invalid:
            print(f"ERRO: features invalidas: {invalid}")
            print(f"Disponiveis: {sorted(FEATURE_FLAGS)}")
            sys.exit(2)
        force_feats = feats

    report = run_reconciliation(
        raw_dir=raw,
        merged_output_base=merged_base,
        previous_merged=prev_merged,
        force_refetch_features=force_feats,
        full=args.full,
    )

    print("\n" + report.summary())
    if report.aborted:
        print(f"ABORTADO: {report.abort_reason}")
        sys.exit(3)
    if report.warnings:
        print(f"\nWarnings ({len(report.warnings)}) primeiros 10:")
        for w in report.warnings[:10]:
            print(f"  {w}")
    print(f"\nMerged em: {merged_base}")


if __name__ == "__main__":
    main()
