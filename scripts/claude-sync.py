"""Sync Claude.ai — captura + assets + reconcile em uma rodada.

Espelho de scripts/chatgpt-sync.py e perplexity-sync.py.

Etapas:
    1. Capture     -> data/raw/Claude.ai/ (cumulativo)
    2. Assets      -> binarios + artifacts extraidos (skip-existing)
    3. Reconcile   -> data/merged/Claude.ai/ (cumulativo, com preservation)

Flags:
    --no-binaries     pula etapa 2 (so capture + reconcile)
    --no-reconcile    pula etapa 3 (so capture + assets)
    --full            forca refetch full (vs incremental)
    --dry-run         reporta o que faria, nao executa
    --thumbnail       baixa variant thumbnail tambem (alem de preview)
    --profile NAME    profile Playwright (default='default')

Uso: python scripts/claude-sync.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from src.extractors.claude_ai.api_client import ClaudeAPIClient
from src.extractors.claude_ai.asset_downloader import download_assets, extract_artifacts
from src.extractors.claude_ai.auth import load_context
from src.extractors.claude_ai.orchestrator import BASE_DIR as RAW_DIR, run_export
from src.reconcilers.claude_ai import run_reconciliation


MERGED_DIR = Path("data/merged/Claude.ai")


def _section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


async def _run_assets(
    raw_dir: Path,
    profile: str,
    include_thumbnail: bool,
) -> dict:
    """Etapa 2: extract artifacts (offline) + download binarios (API)."""
    print("Extraindo artifacts (code/markdown/html/react/...)...")
    art_stats = extract_artifacts(raw_dir)
    print(f"  artifacts extraidos: {art_stats['extracted']}")
    print(f"  ja existentes:      {art_stats['skipped_existing']}")
    if art_stats["errors"]:
        print(f"  erros: {len(art_stats['errors'])}")

    print("\nBaixando binarios (imagens) via API...")
    context, org_id = await load_context(profile_name=profile, headless=True)
    client = ClaudeAPIClient(context, org_id)
    try:
        stats = await download_assets(
            client, raw_dir, include_thumbnail=include_thumbnail
        )
    finally:
        await context.close()

    print(
        f"  downloaded={stats['downloaded']} "
        f"skipped={stats['skipped_existing']} "
        f"blob={stats['not_downloadable_blob']} "
        f"err={len(stats['errors'])}"
    )
    return {"artifacts": art_stats, "binaries": stats}


async def main(args: argparse.Namespace) -> int:
    started = time.time()

    if args.dry_run:
        _section("DRY RUN (sem efeitos)")
        print(f"  Capture seria escrita em: {RAW_DIR}")
        print(f"  Assets em:               {RAW_DIR / 'assets'}")
        print(f"  Reconcile seria em:      {MERGED_DIR}")
        print(f"  Modo:                    {'full' if args.full else 'incremental'}")
        print(f"  Etapa 2 (assets):        {'skipped' if args.no_binaries else 'run'}")
        print(f"  Etapa 3 (reconcile):     {'skipped' if args.no_reconcile else 'run'}")
        return 0

    # ============================================================
    # Etapa 1: Capture
    # ============================================================
    _section("Etapa 1/3 — Capture")
    try:
        raw_dir = await run_export(
            profile_name=args.profile,
            full=args.full,
            smoke_limit=args.smoke,
        )
    except Exception as e:
        print(f"\nERRO na captura: {e}")
        return 1
    print(f"\nCapture OK em: {raw_dir}")

    # ============================================================
    # Etapa 2: Assets (binarios + artifacts)
    # ============================================================
    if not args.no_binaries:
        _section("Etapa 2/3 — Assets (binarios + artifacts)")
        try:
            await _run_assets(
                raw_dir,
                profile=args.profile,
                include_thumbnail=args.thumbnail,
            )
        except Exception as e:
            print(f"\nERRO em assets: {e}")
            return 1
    else:
        print("\n--no-binaries setado, pulando etapa 2.")

    # ============================================================
    # Etapa 3: Reconcile
    # ============================================================
    if not args.no_reconcile:
        _section("Etapa 3/3 — Reconcile")
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
    else:
        print("\n--no-reconcile setado, pulando etapa 3.")

    print(f"\nTotal elapsed: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--no-binaries", action="store_true",
                        help="Pula etapa 2 (so capture + reconcile)")
    parser.add_argument("--no-reconcile", action="store_true",
                        help="Pula etapa 3 (so capture + assets)")
    parser.add_argument("--full", action="store_true",
                        help="Refetch full (vs incremental)")
    parser.add_argument("--thumbnail", action="store_true",
                        help="Baixa variant thumbnail tambem")
    parser.add_argument("--profile", default="default",
                        help="Profile Playwright (default: 'default')")
    parser.add_argument("--smoke", type=int, default=None,
                        help="Limita N convs (smoke test)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Reporta sem executar")
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args)))
