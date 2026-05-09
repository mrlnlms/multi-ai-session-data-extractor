"""Asset downloader Kimi: baixa files que vem inline em chat.files[].

Cada chat na listagem retorna `files: [{id, meta, blob: {signUrl,
previewUrl}, ...}]`. signUrl tem TTL — refrescar via GetChat antes de
baixar quando expirado. Pra primeira pass, baixa direto via signUrl
(GET, sem auth — URLs sao pre-assinadas).

Layout: data/raw/Kimi/assets/<chat_id>/<file_id>.<ext> (mime -> ext).
Manifest em assets_manifest.json: {file_id: {chat_id, url, relpath,
size, mime, name}}.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from playwright.async_api import BrowserContext


HOME_URL = "https://www.kimi.com/"

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


def _ext_for(mime: str, ext_hint: str | None) -> str:
    if ext_hint:
        e = ext_hint if ext_hint.startswith(".") else "." + ext_hint
        if len(e) <= 8:
            return e
    if mime in MIME_EXT:
        return MIME_EXT[mime]
    guess = mimetypes.guess_extension((mime or "").split(";")[0].strip())
    return guess or ".bin"


async def download_assets(
    context: BrowserContext,
    raw_dir: Path,
    skip_existing: bool = True,
) -> dict:
    """Baixa todos os files inline em chat.files[]. Manifesta em assets_manifest.json."""
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists():
        return {"downloaded": 0, "skipped": 0, "errors": []}

    out_dir = raw_dir / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "assets_manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    page = await context.new_page()
    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1500)

    stats = {"downloaded": 0, "skipped": 0, "errors": []}
    pairs: list[tuple[str, str, dict]] = []  # (chat_id, file_id, file_obj)
    for fp in sorted(conv_dir.glob("*.json")):
        try:
            obj = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        chat = obj.get("chat") or {}
        cid = chat.get("id")
        if not cid:
            continue
        for fobj in chat.get("files") or []:
            fid = fobj.get("id")
            if not fid:
                continue
            pairs.append((cid, fid, fobj))

    total = len(pairs)
    print(f"  {total} files to consider")

    for i, (cid, fid, fobj) in enumerate(pairs, start=1):
        meta = fobj.get("meta") or {}
        mime = meta.get("contentType") or "application/octet-stream"
        ext = _ext_for(mime, meta.get("ext"))
        chat_subdir = out_dir / cid
        chat_subdir.mkdir(parents=True, exist_ok=True)
        dst = chat_subdir / f"{fid}{ext}"

        if skip_existing and dst.exists():
            stats["skipped"] += 1
            manifest[fid] = {
                "chat_id": cid,
                "url": (fobj.get("blob") or {}).get("signUrl") or "",
                "relpath": str(dst.relative_to(raw_dir)),
                "size": dst.stat().st_size,
                "mime": mime,
                "name": meta.get("name") or "",
            }
            if i % 5 == 0:
                print(f"  [{i}/{total}] dl={stats['downloaded']} skip={stats['skipped']} err={len(stats['errors'])}")
            continue

        url = (fobj.get("blob") or {}).get("signUrl")
        if not url:
            stats["errors"].append((fid, "no signUrl"))
            continue
        try:
            b64 = await page.evaluate("""async (url) => {
                const r = await fetch(url, {credentials: 'omit'});
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
            manifest[fid] = {
                "chat_id": cid,
                "url": url,
                "relpath": str(dst.relative_to(raw_dir)),
                "size": len(data),
                "mime": mime,
                "name": meta.get("name") or "",
            }
            stats["downloaded"] += 1
        except Exception as e:
            stats["errors"].append((fid, str(e)[:200]))

        if i % 5 == 0:
            print(f"  [{i}/{total}] dl={stats['downloaded']} skip={stats['skipped']} err={len(stats['errors'])}")

    print(f"  [{total}/{total}] dl={stats['downloaded']} skip={stats['skipped']} err={len(stats['errors'])} (final)")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats
