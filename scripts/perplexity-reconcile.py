"""Reconciler Perplexity."""

import argparse
import sys
from pathlib import Path

from src.reconcilers.perplexity import run_reconciliation, FEATURE_FLAGS


def _find_latest_raw() -> Path | None:
    base = Path("data/raw/Perplexity Data")
    if not base.exists():
        return None
    cs = sorted([p for p in base.iterdir() if p.is_dir() and len(p.name) == 16],
                key=lambda p: p.stat().st_mtime)
    return cs[-1] if cs else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("raw_dir", nargs="?", default=None)
    p.add_argument("--full", action="store_true")
    p.add_argument("--refetch-features", default=None)
    p.add_argument("--previous-merged", default=None)
    a = p.parse_args()

    raw = Path(a.raw_dir) if a.raw_dir else _find_latest_raw()
    if not raw:
        print("ERRO: nenhum raw em data/raw/Perplexity Data/"); sys.exit(1)
    print(f"Raw: {raw}")

    merged_base = Path("data/merged/Perplexity")
    prev = Path(a.previous_merged) if a.previous_merged else None

    force_feats = None
    if a.refetch_features:
        feats = {f.strip() for f in a.refetch_features.split(",") if f.strip()}
        invalid = feats - FEATURE_FLAGS
        if invalid:
            print(f"ERRO: features invalidas: {invalid}; disponiveis: {sorted(FEATURE_FLAGS)}")
            sys.exit(2)
        force_feats = feats

    r = run_reconciliation(raw, merged_base, prev, force_feats, a.full)
    print("\n" + r.summary())
    if r.aborted: print(f"ABORTADO: {r.abort_reason}"); sys.exit(3)
    if r.warnings:
        print(f"\nWarnings ({len(r.warnings)}) primeiros 5:")
        for w in r.warnings[:5]: print(f"  {w}")
    print(f"\nMerged em: {merged_base}")


if __name__ == "__main__":
    main()
