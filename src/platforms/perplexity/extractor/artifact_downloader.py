"""Download dos binarios de Artifacts (UI: Artifacts / API: assets) Perplexity.

Distinto do asset_downloader.py (legacy, que cobre uploads do user em threads
via /rest/file-repository/*). Este modulo cobre os artifacts retornados por
/rest/assets/ — saidas geradas pela IA (CODE_FILE markdown, CHART png,
GENERATED_IMAGE png).

URLs sao:
  - cloudfront.net/web/direct-files/...    (assinadas com Policy/Signature)
  - user-gen-media-assets.s3.amazonaws.com/seedream_images/... (S3 signed)

Output:
  assets/files/{asset_slug}.{ext}     # binarios baixados
  assets/files/_manifest.json         # mapping completo

Idempotente: skip se arquivo ja existe.
"""

import json
import re
from pathlib import Path
from playwright.async_api import BrowserContext


def _ext_from_url_or_type(url: str, asset_type: str | None) -> str:
    """Determina extensao do arquivo a partir da URL ou asset_type."""
    base = url.split("?")[0]
    m = re.search(r'\.([a-z0-9]{1,5})$', base, re.I)
    if m:
        return f".{m.group(1).lower()}"
    if asset_type == "GENERATED_IMAGE":
        return ".png"
    if asset_type == "CODE_FILE":
        return ".md"
    if asset_type == "CHART":
        return ".png"
    return ".bin"


async def download_artifacts(
    context: BrowserContext,
    artifacts: list[dict],
    output_dir: Path,
) -> dict:
    """Baixa binarios dos artifacts via APIRequestContext (cookies-aware)."""
    files_dir = output_dir / "assets" / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    ok = 0
    skipped = 0
    failed = 0

    for art in artifacts:
        location = art.get("location")
        slug = art.get("asset_slug")
        asset_type = art.get("asset_type")

        if not location or not slug:
            manifest.append({"slug": slug or "unknown", "status": "skipped_no_url"})
            continue

        ext = _ext_from_url_or_type(location, asset_type)
        out_path = files_dir / f"{slug}{ext}"

        if out_path.exists():
            skipped += 1
            manifest.append({
                "slug": slug,
                "status": "skipped_existing",
                "path": str(out_path.relative_to(output_dir)),
                "asset_type": asset_type,
                "bytes": out_path.stat().st_size,
            })
            continue

        try:
            response = await context.request.get(location, timeout=60000)
            if not response.ok:
                failed += 1
                manifest.append({
                    "slug": slug,
                    "status": "error",
                    "asset_type": asset_type,
                    "error": f"HTTP {response.status}",
                })
                continue
            body = await response.body()
            out_path.write_bytes(body)
            ok += 1
            manifest.append({
                "slug": slug,
                "status": "ok",
                "path": str(out_path.relative_to(output_dir)),
                "asset_type": asset_type,
                "bytes": len(body),
                "caption": art.get("caption"),
            })
        except Exception as e:
            failed += 1
            manifest.append({
                "slug": slug,
                "status": "error",
                "asset_type": asset_type,
                "error": str(e)[:200],
            })

    with open(files_dir / "_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return {
        "downloaded": ok,
        "skipped_existing": skipped,
        "failed": failed,
        "total": len(artifacts),
    }
