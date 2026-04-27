"""Sync ChatGPT — captura tudo em uma rodada, pasta unica cumulativa.

Uso:
    python scripts/chatgpt-sync.py [--no-voice-pass] [--full] [--no-binaries]

4 etapas (transparentes pro usuario):
    1. Captura conversas (extractor + fail-fast contra discovery flakey)
       - Mutacao in-place em data/raw/ChatGPT/
       - chatgpt_raw.json sobrescreve, capture_log.jsonl append
    2. Download assets DELTA (Canvas + Deep Research extraidos do raw,
       imagens via API — script ja faz skip de existentes)
    3. Download project_sources DELTA (knowledge files dos projects,
       _files.json com preservation pra sources removidas no servidor)
    4. Reconcile -> merged cumulativo em data/merged/ChatGPT/
       - chatgpt_merged.json sobrescreve, reconcile_log.jsonl append

Pra rodar so um passo, use os scripts standalone:
    python scripts/chatgpt-export.py
    python scripts/chatgpt-download-assets.py data/raw/ChatGPT
    python scripts/chatgpt-download-project-sources.py data/raw/ChatGPT
    python scripts/chatgpt-reconcile.py data/raw/ChatGPT

Requer login previo:
    python scripts/chatgpt-login.py
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from src.extractors.chatgpt.api_client import ChatGPTAPIClient
from src.extractors.chatgpt.asset_downloader import (
    extract_canvases,
    extract_deep_research,
    run_asset_download,
)
from src.extractors.chatgpt.auth import get_profile_dir
from src.extractors.chatgpt.models import CaptureOptions
from src.extractors.chatgpt.orchestrator import run_capture
from src.extractors.chatgpt.project_sources import download_project_sources
from src.reconcilers.chatgpt import run_reconciliation


def _default_output_dir() -> Path:
    """Pasta unica cumulativa — sempre o mesmo path."""
    return Path("data/raw/ChatGPT")


async def _download_project_sources_for(raw_dir: Path) -> dict:
    """Wrapper async que abre Playwright e baixa project_sources delta."""
    import json
    raw_path = raw_dir / "chatgpt_raw.json"
    if not raw_path.exists():
        return {"project_ids": 0, "downloaded": 0}
    with open(raw_path, encoding="utf-8") as f:
        data = json.load(f)
    convs = data.get("conversations", {})
    if isinstance(convs, dict):
        convs_iter = convs.values()
    else:
        convs_iter = convs
    pids = sorted({c.get("_project_id") or c.get("gizmo_id")
                   for c in convs_iter
                   if (c.get("_project_id") or c.get("gizmo_id") or "").startswith("g-p-")})
    if not pids:
        return {"project_ids": 0, "downloaded": 0}

    profile_dir = get_profile_dir()
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir), headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        client = ChatGPTAPIClient(context.request)
        report = await download_project_sources(client, pids, raw_dir)
        await context.close()
    return {"project_ids": len(pids), **report}


def main():
    parser = argparse.ArgumentParser(
        description="Captura + binarios + reconcile ChatGPT em uma rodada"
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--no-voice-pass", action="store_true",
                       help="Pula DOM voice pass na captura")
    parser.add_argument("--dry-run", action="store_true",
                       help="So descoberta, nao baixa, nao reconcilia")
    parser.add_argument("--full", action="store_true",
                       help="Forca brute force na captura de conversas")
    parser.add_argument("--no-binaries", action="store_true",
                       help="Pula etapas 2-3 (so captura + reconcile)")
    parser.add_argument("--no-reconcile", action="store_true",
                       help="Pula etapa 4 (reconciliacao)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")

    output_dir = args.output_dir or _default_output_dir()
    options = CaptureOptions(
        skip_voice=args.no_voice_pass,
        dry_run=args.dry_run,
        full=args.full,
    )

    # ETAPA 1: Captura (in-place na pasta unica)
    print("=" * 60)
    print("ETAPA 1/4: Captura de conversas")
    print("=" * 60)
    capture_report = asyncio.run(run_capture(output_dir, options))
    print("\n" + capture_report.summary())

    if args.dry_run:
        print("\n[dry-run: pulando demais etapas]")
        return

    # Pasta unica — sem resolucao de sufixo de hora
    actual_raw_dir = output_dir

    if not args.no_binaries:
        # ETAPA 2: Download assets delta
        print("\n" + "=" * 60)
        print("ETAPA 2/4: Download assets (delta)")
        print("=" * 60)
        c = extract_canvases(actual_raw_dir)
        print(f"Canvas: extracted={c['extracted']}, skip={c['skipped_existing']}, err={len(c['errors'])}")
        r = extract_deep_research(actual_raw_dir)
        print(f"Deep Research: extracted={r['extracted']}, skip={r['skipped_existing']}, err={len(r['errors'])}")
        asset_report = asyncio.run(run_asset_download(actual_raw_dir))
        print(asset_report.summary())

        # ETAPA 3: Download project_sources delta
        print("\n" + "=" * 60)
        print("ETAPA 3/4: Download project sources (delta)")
        print("=" * 60)
        ps_report = asyncio.run(_download_project_sources_for(actual_raw_dir))
        print(f"Projects scaneados: {ps_report.get('projects_scanned', 0)} "
              f"({ps_report.get('projects_with_files', 0)} com files)")
        print(f"Files: total={ps_report.get('total_files', 0)}, "
              f"downloaded={ps_report.get('downloaded', 0)}, "
              f"skipped={ps_report.get('skipped_existing', 0)}, "
              f"errors={len(ps_report.get('errors', []))}")

    if args.no_reconcile:
        print("\n[--no-reconcile: pulando reconciliacao]")
        return

    # ETAPA 4: Reconcile
    print("\n" + "=" * 60)
    print("ETAPA 4/4: Reconciliacao")
    print("=" * 60)
    merged_base = Path("data/merged/ChatGPT")
    reconcile_report = run_reconciliation(actual_raw_dir, merged_base)
    if reconcile_report.aborted:
        print(f"\nRECONCILER ABORTOU: {reconcile_report.abort_reason}")
        sys.exit(1)
    print("\n" + reconcile_report.summary())

    # Resumo final
    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"Raw:    {actual_raw_dir}/")
    print(f"Merged: {merged_base}/")


if __name__ == "__main__":
    main()
