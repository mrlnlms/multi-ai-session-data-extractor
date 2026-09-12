"""Reconciler Claude.ai standalone.

Uso:
    python scripts/claude-reconcile.py            # raw=data/raw/Claude.ai/, merged=data/merged/Claude.ai/
    python scripts/claude-reconcile.py --full
    python scripts/claude-reconcile.py --refetch-features attachments_extracted_content

Default: pasta unica cumulativa. claude-sync.py ja chama internamente.
"""

import argparse
import sys
from pathlib import Path

from src.extractors.claude_ai.orchestrator import BASE_DIR as RAW_DIR
from src.reconcilers.claude_ai import run_reconciliation, FEATURE_FLAGS


MERGED_DIR = Path("data/merged/Claude.ai")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("raw_dir", nargs="?", default=None,
                        help=f"Raw dir (default: {RAW_DIR})")
    parser.add_argument("--full", action="store_true",
                        help="Forca to_use em tudo (refetch completo)")
    parser.add_argument("--refetch-features", default=None,
                        help=f"Lista csv de features a forcar refetch (disponiveis: {','.join(sorted(FEATURE_FLAGS))})")
    parser.add_argument("--previous-merged", default=None,
                        help="Override do merged anterior (default: pasta unica self-merge)")
    args = parser.parse_args()

    raw = Path(args.raw_dir) if args.raw_dir else RAW_DIR
    if not raw.exists() or not (raw / "discovery_ids.json").exists():
        print(f"ERRO: raw nao encontrado em {raw}. Rode scripts/claude-export.py primeiro.")
        sys.exit(1)
    print(f"Raw: {raw}")

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
        merged_output=MERGED_DIR,
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
    print(f"\nMerged em: {MERGED_DIR}")


if __name__ == "__main__":
    main()
