"""Download binarios (imagens) dos files referenciados no raw atual.

Uso: python scripts/claude-download-assets.py [raw_dir]
Se nao passar raw_dir, usa data/raw/Claude.ai/ (pasta unica cumulativa).

Flags:
  --thumbnail    tambem baixa variant thumbnail (400px)
  --profile      profile Playwright
"""

import argparse
import asyncio
import sys
from pathlib import Path

from src.extractors.claude_ai.auth import load_context
from src.extractors.claude_ai.api_client import ClaudeAPIClient
from src.extractors.claude_ai.asset_downloader import download_assets, extract_artifacts
from src.extractors.claude_ai.orchestrator import BASE_DIR


def _default_raw() -> Path | None:
    """Pasta unica cumulativa (data/raw/Claude.ai/). Backward compat com layout antigo."""
    if BASE_DIR.exists() and (BASE_DIR / "conversations").exists():
        return BASE_DIR
    # Backward compat: layout antigo timestampado
    base = Path("data/raw")
    if not base.exists():
        return None
    legacy = sorted(
        [p for p in base.iterdir() if p.is_dir() and p.name.startswith("Claude Data ")],
        key=lambda p: p.stat().st_mtime,
    )
    return legacy[-1] if legacy else None


async def main(raw_dir: Path, include_thumbnail: bool, profile: str, skip_binaries: bool):
    # Artifacts extraction e offline (le raw). Roda primeiro.
    print("Extraindo artifacts (code/markdown/html/react/...)...")
    art_stats = extract_artifacts(raw_dir)
    print(f"  artifacts extraidos: {art_stats['extracted']}")
    print(f"  ja existentes: {art_stats['skipped_existing']}")
    if art_stats["by_type"]:
        print(f"  por type:")
        for t, c in sorted(art_stats["by_type"].items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {c:5} {t}")
    if art_stats["errors"]:
        print(f"  erros: {len(art_stats['errors'])}")

    if skip_binaries:
        return

    # Download de binarios (imagens) via API
    context, org_id = await load_context(profile_name=profile, headless=True)
    client = ClaudeAPIClient(context, org_id)
    try:
        stats = await download_assets(
            client, raw_dir, include_thumbnail=include_thumbnail
        )
        print(f"\n=== SUMMARY ===")
        print(f"  artifacts: {art_stats['extracted']}")
        print(f"  downloaded: {stats['downloaded']}")
        print(f"  skipped (ja existia): {stats['skipped_existing']}")
        print(f"  blobs nao-baixaveis: {stats['not_downloadable_blob']}")
        print(f"  erros: {len(stats['errors'])}")
        if stats["errors"]:
            print("Primeiros erros:")
            for fu, msg in stats["errors"][:5]:
                print(f"  {fu}: {msg}")
    finally:
        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download assets do Claude.ai raw")
    parser.add_argument("raw_dir", nargs="?", default=None, help="Raw dir (default: mais recente)")
    parser.add_argument("--thumbnail", action="store_true", help="Baixa variant thumbnail tambem")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--artifacts-only", action="store_true", help="So extrai artifacts, pula download de binarios")
    args = parser.parse_args()

    if args.raw_dir:
        raw = Path(args.raw_dir)
    else:
        raw = _default_raw()
        if not raw:
            print("ERRO: nao foi possivel achar raw — rode scripts/claude-export.py primeiro")
            sys.exit(1)
        print(f"Usando raw: {raw}")

    asyncio.run(main(raw, args.thumbnail, args.profile, args.artifacts_only))
