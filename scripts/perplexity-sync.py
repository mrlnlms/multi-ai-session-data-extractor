"""Sync Perplexity: orquestra capture + reconcile end-to-end.

Espelho do scripts/chatgpt-sync.py. Mais simples por estrutura (Perplexity
ja faz tudo num shot — threads + spaces + pages + assets metadata + binarios
+ thread attachments — tudo no orchestrator do extractor).

Etapas:
  1. capture      → data/raw/Perplexity/ (cumulativo)
  2. reconcile    → data/merged/Perplexity/ (cumulativo, com preservation)

Flags:
  --no-reconcile  pula reconcile (so capture)
  --full          forca refetch de todos threads (vs incremental)
  --dry-run       so reporta o que faria, nao executa

Uso: python scripts/perplexity-sync.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from src.extractors.perplexity.orchestrator import run_export, BASE_DIR as RAW_DIR
from src.reconcilers.perplexity import run_reconciliation


MERGED_DIR = Path("data/merged/Perplexity")


def _section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


async def main(args: argparse.Namespace) -> int:
    started = time.time()

    if args.dry_run:
        _section("DRY RUN (sem efeitos)")
        print(f"  Capture seria escrita em: {RAW_DIR}")
        print(f"  Reconcile seria escrita em: {MERGED_DIR}")
        print(f"  Modo: {'full' if args.full else 'incremental'}")
        print(f"  Reconcile: {'skipped' if args.no_reconcile else 'run'}")
        return 0

    # ============================================================
    # Etapa 1: Capture
    # ============================================================
    _section("Etapa 1/2 — Capture")
    try:
        raw_dir = await run_export(full=args.full, account=args.account)
    except Exception as e:
        print(f"\nERRO na captura: {e}")
        return 1
    print(f"\nCapture OK em: {raw_dir}")

    if args.no_reconcile:
        print("\n--no-reconcile setado, pulando etapa 2.")
        return 0

    # ============================================================
    # Etapa 2: Reconcile
    # ============================================================
    _section("Etapa 2/2 — Reconcile")
    report = run_reconciliation(raw_dir, MERGED_DIR)
    print(report.summary())
    if report.aborted:
        print(f"  ABORTED: {report.abort_reason}")
        return 2
    if report.warnings:
        print(f"  Warnings ({len(report.warnings)}):")
        for w in report.warnings[:5]:
            print(f"    - {w}")
    print(f"\nMerged em: {MERGED_DIR}")
    print(f"Total elapsed: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-reconcile", action="store_true", help="Pula reconcile")
    parser.add_argument("--full", action="store_true", help="Refetch todas as threads")
    parser.add_argument("--account", default="default", help="Conta Perplexity (default: 'default')")
    parser.add_argument("--dry-run", action="store_true", help="Reporta sem executar")
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args)))
