"""Asset downloader Grok: baixa binarios via assets.grok.com.

URL deterministica: cada asset em assets.json tem campo `key` com path
no formato `users/<user_id>/<asset_id>/content`. URL completa de
download: `https://assets.grok.com/<key>`. Auth via cookies do profile
(same eTLD+1, browser/page envia automaticamente).

Probe 2026-05-09:
  GET https://assets.grok.com/users/<uid>/<aid>/content -> 200
  content-type bate com mimeType da listagem, content-length idem.

Naming local: data/raw/Grok/assets/<asset_id>.<ext> (mime -> ext).
Manifest em data/raw/Grok/assets_manifest.json mapeia
{asset_id: {url, relpath, size, mime}} pra parser resolver asset_path.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from playwright.async_api import BrowserContext


CDN_BASE = "https://assets.grok.com/"
HOME_URL = "https://grok.com/"

# Mapeamento mime -> extensao quando mimetypes.guess_extension falha
# ou retorna alternativa indesejada (ex: image/jpeg -> .jpe).
MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/json": ".json",
}


def _ext_for_mime(mime: str) -> str:
    if mime in MIME_EXT:
        return MIME_EXT[mime]
    guess = mimetypes.guess_extension(mime.split(";")[0].strip())
    return guess or ".bin"


async def download_assets(
    context: BrowserContext,
    raw_dir: Path,
    skip_existing: bool = True,
) -> dict:
    """Baixa todos os assets listados em raw_dir/assets.json.

    Retorna stats: {downloaded, skipped, errors: [(asset_id, msg)]}.
    """
    assets_path = raw_dir / "assets.json"
    if not assets_path.exists():
        print(f"  assets.json nao existe em {raw_dir} — nada pra baixar")
        return {"downloaded": 0, "skipped": 0, "errors": []}

    assets = json.loads(assets_path.read_text(encoding="utf-8"))
    if not assets:
        print("  0 assets na listagem")
        return {"downloaded": 0, "skipped": 0, "errors": []}

    out_dir = raw_dir / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    page = await context.new_page()
    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1500)

    manifest_path = raw_dir / "assets_manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    stats = {"downloaded": 0, "skipped": 0, "errors": []}
    total = len(assets)

    for i, a in enumerate(assets, start=1):
        aid = a.get("assetId")
        key = a.get("key")
        mime = a.get("mimeType") or "application/octet-stream"
        if not aid or not key:
            stats["errors"].append((aid or "?", "missing assetId or key"))
            continue

        ext = _ext_for_mime(mime)
        dst = out_dir / f"{aid}{ext}"

        if skip_existing and dst.exists():
            stats["skipped"] += 1
            manifest[aid] = {
                "url": CDN_BASE + key,
                "relpath": str(dst.relative_to(raw_dir)),
                "size": dst.stat().st_size,
                "mime": mime,
            }
            if i % 10 == 0:
                print(f"  [{i}/{total}] dl={stats['downloaded']} skip={stats['skipped']} err={len(stats['errors'])}")
            continue

        url = CDN_BASE + key
        try:
            # Fetch via page.evaluate (cookies do profile herdados) e
            # serializa como base64 pra retornar bytes
            b64 = await page.evaluate("""async (url) => {
                const r = await fetch(url, {credentials: 'include'});
                if (!r.ok) throw new Error('HTTP ' + r.status);
                const buf = await r.arrayBuffer();
                let binary = '';
                const bytes = new Uint8Array(buf);
                for (let i = 0; i < bytes.byteLength; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                return btoa(binary);
            }""", url)
            data = base64.b64decode(b64)
            dst.write_bytes(data)
            manifest[aid] = {
                "url": url,
                "relpath": str(dst.relative_to(raw_dir)),
                "size": len(data),
                "mime": mime,
            }
            stats["downloaded"] += 1
        except Exception as e:
            stats["errors"].append((aid, str(e)[:200]))

        if i % 10 == 0:
            print(f"  [{i}/{total}] dl={stats['downloaded']} skip={stats['skipped']} err={len(stats['errors'])}")

    print(f"  [{total}/{total}] dl={stats['downloaded']} skip={stats['skipped']} err={len(stats['errors'])} (final)")

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats
