"""Asset downloader Qwen: baixa uploads do user + imagens/videos gerados pelo modelo.

Fontes de URLs nos raws:
  1. data.chat.history.messages[*].files[*].url
     - User uploads (PDFs, imagens, docs) com URL presigned em cdn.qwenlm.ai/{user_id}/
     - `file_class` pode ser: document, image, url (esse ultimo e url_parse — skip)
  2. data.chat.history.messages[*].content_list[*].content
     - Quando conv_type e t2i/t2v, content do assistant e URL direta pro asset gerado
     - URLs cdn.qwenlm.ai/output/{user_id}/t2i/{conv_id}/ ou /t2v/

Naming:
  - User uploads: {conv_id}/{file_name_original} — preserva nome legivel
  - Imagens geradas: {conv_id}/gen_{hash}.{ext}
  - Manifest em assets_manifest.json com mapping hash→{url, conv_id, filename, source_type, size}
"""

import asyncio
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import BrowserContext


CDN_UPLOAD_RE = re.compile(r'^https://cdn\.qwenlm\.ai/[0-9a-f\-]{36}/[0-9a-f\-]{36}_')
CDN_OUTPUT_RE = re.compile(r'^https://cdn\.qwenlm\.ai/output/')

# Regex pra achar qualquer URL qwen/alibaba no JSON serializado — pega tb
# artefatos gerados em campos aninhados (image_list, slide_pages, deep_research).
ANY_ASSET_URL_RE = re.compile(
    r'https://(?:cdn\.qwenlm\.ai|[a-z0-9\-]+\.oss[a-z0-9\-]*\.aliyuncs\.com)/[^"\\\s]+'
)


def _collect_urls(raw_dir: Path) -> dict[str, dict]:
    """Varre raw, retorna {url: {conv_id, source_type, file_name?}}.

    source_type: user_upload | generated | project_file
    """
    conv_dir = raw_dir / "conversations"
    urls: dict[str, dict] = {}

    # 0) Files anexados a projects (via projects.json._files[*].path)
    projects_path = raw_dir / "projects.json"
    if projects_path.exists():
        try:
            projects = json.loads(projects_path.read_text(encoding="utf-8"))
        except Exception:
            projects = []
        for p in projects:
            pid = p.get("id")
            for f in p.get("_files") or []:
                url = f.get("path")
                if not isinstance(url, str) or not url.startswith("https://"):
                    continue
                urls.setdefault(url, {
                    "conv_id": f"_project_{pid}",
                    "source_type": "project_file",
                    "file_name": f.get("file_name"),
                    "file_class": None,
                    "file_id": f.get("file_id"),
                    "project_id": pid,
                })

    if not conv_dir.exists():
        return urls
    for jp in conv_dir.glob("*.json"):
        try:
            with open(jp, encoding="utf-8") as f:
                envelope = json.load(f)
        except Exception:
            continue
        conv = envelope.get("data", {}) or {}
        conv_id = conv.get("id") or jp.stem
        messages = (conv.get("chat", {}) or {}).get("history", {}).get("messages", {}) or {}
        for _mid, msg in messages.items():
            # 1) files uploaded
            for f in msg.get("files") or []:
                url = f.get("url")
                if not isinstance(url, str) or not url.startswith("https://"):
                    continue
                if f.get("file_class") == "url":
                    # qwen_url_parse_to_markdown — nao e asset baixavel
                    continue
                urls.setdefault(url, {
                    "conv_id": conv_id,
                    "source_type": "user_upload",
                    "file_name": f.get("name"),
                    "file_class": f.get("file_class"),
                    "size_hint": f.get("size"),
                    "file_id": f.get("id"),
                })
            # 2) generated content (t2i/t2v/image_gen/slides/PdfMdGen/etc)
            # Serializa msg inteira e pesca URLs qwen/aliyun. Captura tb
            # URLs em campos aninhados (extra.image_list, extra.slides.slide_pages,
            # extra.deep_research.pdf.link, extra.tool_result, etc).
            try:
                serialized = json.dumps(msg, ensure_ascii=False)
            except Exception:
                serialized = ""
            for match in ANY_ASSET_URL_RE.finditer(serialized):
                url = match.group(0)
                # Skip files ja coletados como user_upload (tem UUID_UUID_ no path)
                if CDN_UPLOAD_RE.match(url):
                    continue
                # Classifica por phase do content_list pai (aproximado) ou pelo path
                file_class = "generated"
                if "/image_gen/" in url:
                    file_class = "image_gen"
                elif "/t2i/" in url:
                    file_class = "t2i"
                elif "/t2v/" in url:
                    file_class = "t2v"
                elif ".pdf" in url.lower():
                    file_class = "deep_research_pdf"
                elif url.endswith(".md") or ".md?" in url:
                    file_class = "deep_research_md"
                urls.setdefault(url, {
                    "conv_id": conv_id,
                    "source_type": "generated",
                    "file_name": None,
                    "file_class": file_class,
                })
    return urls


def _safe_filename(name: str) -> str:
    """Remove caracteres problematicos em filesystem."""
    return re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)[:200]


def _target_path(assets_dir: Path, url: str, info: dict, content_type: str) -> Path:
    conv_id = info["conv_id"]
    folder = assets_dir / conv_id
    folder.mkdir(parents=True, exist_ok=True)
    if info["source_type"] in ("user_upload", "project_file") and info.get("file_name"):
        return folder / _safe_filename(info["file_name"])
    # Pra generated: tenta pegar nome do path (ex: deep research PDF tem titulo no URL)
    from urllib.parse import urlparse, unquote
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    path_name = urlparse(url).path.rsplit("/", 1)[-1]
    if path_name and "." in path_name and len(path_name) < 180:
        # Decode URL encoding (titulos em portugues vem encoded)
        name = _safe_filename(unquote(path_name))
        return folder / f"{info.get('file_class', 'gen')}_{h}_{name}"
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
    prefix = info.get("file_class") or "gen"
    return folder / f"{prefix}_{h}{ext}"


async def download_assets(
    context: BrowserContext,
    raw_dir: Path,
    concurrency: int = 5,
    skip_existing: bool = True,
) -> dict:
    # Abre uma page pra ter acesso ao endpoint /api/v1/files/{id}/content
    # como fallback quando a URL direta do CDN retorna 404.
    page = await context.new_page()
    await page.goto("https://chat.qwen.ai/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)
    download_assets._page = page  # type: ignore[attr-defined]

    urls_info = _collect_urls(raw_dir)
    print(f"Encontradas {len(urls_info)} URLs unicas de asset")

    assets_dir = raw_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = raw_dir / "assets_manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    sem = asyncio.Semaphore(concurrency)
    stats = {"downloaded": 0, "skipped": 0, "errors": []}
    done = 0
    total = len(urls_info)

    async def _try_api_content_fallback(file_id: str) -> tuple[bytes, str] | None:
        """Fallback: GET /api/v1/files/{id}/content via page.evaluate.

        Retorna (blob, content_type) ou None se falhar.
        """
        try:
            # page precisa estar disponivel. Se nao tiver, pula.
            page = getattr(download_assets, "_page", None)
            if page is None:
                return None
            result = await page.evaluate("""async (fid) => {
                const res = await fetch(`/api/v1/files/${fid}/content`, {
                    headers: {'source': 'web', 'bx-v': '2.5.36'}
                });
                if (!res.ok) return {error: res.status};
                const buf = await res.arrayBuffer();
                // Converte pra base64 pra passar via string
                const bytes = new Uint8Array(buf);
                let bin = '';
                for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
                return {b64: btoa(bin), content_type: res.headers.get('content-type') || 'application/octet-stream'};
            }""", file_id)
            if isinstance(result, dict) and result.get("b64"):
                import base64
                return base64.b64decode(result["b64"]), result.get("content_type", "application/octet-stream")
        except Exception:
            pass
        return None

    async def _one(url: str, info: dict):
        nonlocal done
        h = hashlib.sha1(url.encode()).hexdigest()[:16]
        async with sem:
            if skip_existing and h in manifest:
                existing = assets_dir / manifest[h].get("relpath", "")
                if (assets_dir / existing).exists() or existing.exists():
                    stats["skipped"] += 1
                    done += 1
                    return
            blob = None
            ct = "application/octet-stream"
            # 1) Tenta URL direta
            try:
                resp = await context.request.get(url, timeout=60000)
                if resp.ok:
                    blob = await resp.body()
                    ct = resp.headers.get("content-type", ct)
                else:
                    # 2) Fallback /api/v1/files/{id}/content pra user_uploads
                    file_id = info.get("file_id")
                    if info["source_type"] == "user_upload" and file_id:
                        fb = await _try_api_content_fallback(file_id)
                        if fb:
                            blob, ct = fb
                    if blob is None:
                        stats["errors"].append((url[:100], f"HTTP {resp.status} (fallback api/v1 also failed)"))
                        done += 1
                        return
            except Exception as e:
                stats["errors"].append((url[:100], str(e)[:200]))
                done += 1
                return

            try:
                target = _target_path(assets_dir, url, info, ct)
                target.write_bytes(blob)
                relpath = target.relative_to(assets_dir).as_posix()
                manifest[h] = {
                    "url": url,
                    "conv_id": info["conv_id"],
                    "source_type": info["source_type"],
                    "file_class": info.get("file_class"),
                    "file_name": info.get("file_name"),
                    "file_id": info.get("file_id"),
                    "content_type": ct,
                    "size": len(blob),
                    "relpath": relpath,
                }
                stats["downloaded"] += 1
            except Exception as e:
                stats["errors"].append((url[:100], f"write: {str(e)[:150]}"))
            done += 1
            if done % 20 == 0:
                print(f"  [{done}/{total}] dl={stats['downloaded']} "
                      f"skip={stats['skipped']} err={len(stats['errors'])}")

    await asyncio.gather(*(_one(u, i) for u, i in urls_info.items()))
    await page.close()

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"  [{done}/{total}] dl={stats['downloaded']} "
          f"skip={stats['skipped']} err={len(stats['errors'])} (final)")
    return stats
