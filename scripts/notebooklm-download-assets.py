"""Download de assets NotebookLM (todos os 7 tipos de outputs).

Auto-detecta raw mais recente da conta. Quando ha raw anterior, COPIA assets
ja baixados (skip-existing por path) antes de baixar — evita re-download
massivo de coisas que ja temos.

Uso:
    python scripts/notebooklm-download-assets.py --account hello [raw_dir]
    python scripts/notebooklm-download-assets.py --account marloon --no-copy-prev
"""

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from src.extractors.notebooklm.auth import load_context, VALID_ACCOUNTS, ACCOUNT_LANG
from src.extractors.notebooklm.api_client import NotebookLMClient
from src.extractors.notebooklm.batchexecute import load_session
from src.extractors.notebooklm.asset_downloader import download_assets, fetch_text_artifacts, save_notes_and_mindmaps
from src.extractors.notebooklm.orchestrator import ACCOUNT_DIR_MAP


def _list_raws(account: str) -> list[Path]:
    """Lista raws da conta ordenados do mais antigo pro mais novo."""
    base = Path("data/raw/NotebookLM Data") / ACCOUNT_DIR_MAP[account]
    if not base.exists():
        return []
    return sorted(
        [p for p in base.iterdir() if p.is_dir() and len(p.name) == 16 and "T" in p.name],
        key=lambda p: p.stat().st_mtime,
    )


def _find_latest_raw(account: str) -> Path | None:
    raws = _list_raws(account)
    return raws[-1] if raws else None


def _copy_existing_assets(target_raw: Path, prev_raw: Path) -> dict:
    """Copia (skip-existing) assets do raw anterior pro novo.
    Evita re-baixar coisas que ja temos. Retorna contagem por subdir.
    """
    src_assets = prev_raw / "assets"
    dst_assets = target_raw / "assets"
    if not src_assets.exists() or src_assets == dst_assets:
        return {}
    counts = {}
    for sub in ("audio_overviews", "video_overviews", "slide_decks",
                "text_artifacts", "notes", "mind_maps", "source_pages"):
        s = src_assets / sub
        if not s.exists():
            continue
        d = dst_assets / sub
        d.mkdir(parents=True, exist_ok=True)
        n_copied = 0
        for item in s.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(s)
            tgt = d / rel
            if tgt.exists():
                continue
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, tgt)
            n_copied += 1
        counts[sub] = n_copied
    return counts


async def main(raw_dir: Path, account: str, copy_prev: bool):
    # Pre-passo: copia assets do raw anterior se existir
    if copy_prev:
        raws = _list_raws(account)
        # Procura o anterior ao raw_dir atual (penultimo se raw_dir for o ultimo)
        prev = None
        for i, r in enumerate(raws):
            if r == raw_dir and i > 0:
                prev = raws[i - 1]
                break
        if prev:
            print(f"Copiando assets de raw anterior {prev.name}...")
            counts = _copy_existing_assets(raw_dir, prev)
            total = sum(counts.values())
            if total:
                print(f"  copiados: {total} files ({counts})")
            else:
                print(f"  nada a copiar (raw novo igual ao anterior)")

    context = await load_context(account, headless=True)
    try:
        session = await load_session(context)
        client = NotebookLMClient(context, session, hl=ACCOUNT_LANG[account])
        # Notes + Mind Maps: offline (ja estao no cFji9 capturado)
        nm_stats = save_notes_and_mindmaps(raw_dir)
        # Downloads de midia (audios, videos, slide decks, pages)
        stats = await download_assets(client, raw_dir)
        # Text artifacts (types 2/4/7/9) via v9rmvd
        text_stats = await fetch_text_artifacts(client, raw_dir)
        # Merge
        stats.update(nm_stats)
        stats.update(text_stats)
        stats["errors"].extend(nm_stats.get("errors", []))
        stats["errors"].extend(text_stats.get("errors", []))
        log_path = raw_dir / "assets_log.json"
        log_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
        print(f"\n=== SUMMARY ===")
        print(f"  audios dl:      {stats['audios_downloaded']} skip: {stats['audios_skipped']}")
        print(f"  videos dl:      {stats.get('videos_downloaded',0)} skip: {stats.get('videos_skipped',0)}")
        print(f"  slide decks dl: {stats.get('slide_decks_downloaded',0)} skip: {stats.get('slide_decks_skipped',0)}")
        print(f"  pages dl:       {stats['pages_downloaded']} skip: {stats['pages_skipped']}")
        print(f"  text artifacts: {stats.get('text_artifacts_fetched',0)} skip: {stats.get('text_artifacts_skipped',0)}")
        print(f"  notes saved:    {stats.get('notes_saved',0)} skip: {stats.get('notes_skipped',0)}")
        print(f"  mind maps:      {stats.get('mind_maps_saved',0)} skip: {stats.get('mind_maps_skipped',0)}")
        print(f"  errors:         {len(stats['errors'])}")
    finally:
        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=list(VALID_ACCOUNTS))
    parser.add_argument("raw_dir", nargs="?", default=None)
    parser.add_argument("--no-copy-prev", action="store_true",
                        help="Nao copia assets do raw anterior antes de baixar (default: copia)")
    args = parser.parse_args()
    if args.raw_dir:
        raw = Path(args.raw_dir)
    else:
        raw = _find_latest_raw(args.account)
        if not raw:
            print(f"Nenhum raw achado pra conta {args.account}")
            sys.exit(1)
        print(f"Usando raw: {raw}")
    asyncio.run(main(raw, args.account, copy_prev=not args.no_copy_prev))
