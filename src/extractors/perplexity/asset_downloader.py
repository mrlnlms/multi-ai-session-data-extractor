"""Asset downloader Perplexity: baixa uploads do user + imagens hospedadas no Perplexity.

Filtra URLs externas (imagens web citadas em resultados de busca) — essas sao refs
pra fontes de terceiros e nao devem ser baixadas como assets da conversa.

Fontes baixaveis:
  - ppl-ai-file-upload.s3.amazonaws.com — uploads do usuario (S3 presigned, EXPIRAM)
  - pplx-res.cloudinary.com — imagens hospedadas pela Perplexity
  - perplexity.ai/cdn ou similar — futuro

IMPORTANTE: S3 presigned URLs do ppl-ai-file-upload expiram em ~minutos. Se o
raw ja tem mais que ~5min, as URLs la dentro estao mortas. Solucao: identificar
threads com attachments e re-fetchar fresh antes de baixar.

Origem dos URLs nos raws:
  1. threads/{uuid}.json -> entries[*].attachments (lista de URLs)
  2. threads-index.json -> thread[*].featured_images (metadados)
"""

import asyncio
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import BrowserContext


# Domains que consideramos "assets nativos da conversa"
OWN_DOMAINS = (
    "ppl-ai-file-upload.s3.amazonaws.com",
    "pplx-res.cloudinary.com",
    "perplexity.ai",  # se algum CDN interno
)


def _is_own_asset(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return any(host.endswith(d) for d in OWN_DOMAINS)


def _collect_urls(raw_dir: Path) -> dict[str, dict]:
    urls: dict[str, dict] = {}

    # 1) entries.attachments
    threads_dir = raw_dir / "threads"
    if threads_dir.exists():
        for jp in threads_dir.glob("*.json"):
            try:
                with open(jp, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            thread_uuid = jp.stem
            for entry in data.get("entries", []) or []:
                for att in entry.get("attachments") or []:
                    if isinstance(att, str) and att.startswith("http") and _is_own_asset(att):
                        urls.setdefault(att, {
                            "thread_uuid": thread_uuid,
                            "source_type": "user_upload",
                        })

    # 2) threads-index.featured_images
    idx = raw_dir / "threads-index.json"
    if idx.exists():
        try:
            threads = json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            threads = []
        for t in threads:
            tuuid = t.get("uuid") or ""
            for fi in t.get("featured_images") or []:
                u = fi if isinstance(fi, str) else (fi.get("url") if isinstance(fi, dict) else None)
                if u and u.startswith("http") and _is_own_asset(u):
                    urls.setdefault(u, {
                        "thread_uuid": tuuid,
                        "source_type": "featured_image",
                    })
    return urls


def _target_path(assets_dir: Path, url: str, info: dict, content_type: str) -> Path:
    folder = assets_dir / (info["thread_uuid"] or "unknown")
    folder.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
    # Tenta extrair nome original do path
    path_part = urlparse(url).path.rsplit("/", 1)[-1]
    if path_part and "." in path_part and len(path_part) < 120:
        name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", path_part)
        return folder / f"{h}_{name}"
    prefix = "upload" if info["source_type"] == "user_upload" else "featured"
    return folder / f"{prefix}_{h}{ext}"


async def _refresh_url_via_api(page, stale_url: str) -> str | None:
    """Chama /rest/file-repository/download-attachment pra pegar URL fresh.

    A UI usa esse endpoint: envia a URL antiga (mesmo expirada), backend
    retorna uma nova presigned URL.

    Se o endpoint retornar 404, tenta /download (variante diferente usada
    pra paste.txt). Ambos falhando significa file deletado upstream.
    """
    for ep, field_in, field_out in [
        ("/rest/file-repository/download-attachment", "url", "file_url"),
        ("/rest/file-repository/download", "file_url", "file_url"),
    ]:
        result = await page.evaluate("""async ({ep, payload}) => {
            const res = await fetch(ep + '?version=2.18&source=default', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const txt = await res.text();
            return {status: res.status, body: txt};
        }""", {"ep": ep, "payload": {field_in: stale_url}})
        if result["status"] == 200:
            try:
                parsed = json.loads(result["body"])
                fresh = parsed.get(field_out) or parsed.get("url")
                if fresh:
                    return fresh
            except Exception:
                pass
    return None


async def download_assets(
    context: BrowserContext,
    raw_dir: Path,
    concurrency: int = 5,
    skip_existing: bool = True,
) -> dict:
    # Warmup + pagina pra poder chamar /rest/file-repository/*
    page = await context.new_page()
    await page.goto("https://www.perplexity.ai/library", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)
    title = await page.title()
    if "moment" in title.lower():
        await page.wait_for_timeout(10000)

    urls_info = _collect_urls(raw_dir)
    print(f"Encontradas {len(urls_info)} URLs unicas (filtradas a dominios Perplexity)")

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

    async def _one(stale_url: str, info: dict):
        nonlocal done
        h = hashlib.sha1(stale_url.encode()).hexdigest()[:16]
        async with sem:
            if skip_existing and h in manifest:
                existing = assets_dir / manifest[h].get("relpath", "")
                if existing.exists():
                    stats["skipped"] += 1
                    done += 1
                    return
            # 1) Refresh URL via /rest/file-repository/*
            fresh = await _refresh_url_via_api(page, stale_url)
            if not fresh:
                stats["errors"].append((stale_url[:100], "refresh api returned no fresh URL (file likely deleted upstream)"))
                done += 1
                return
            # 2) Download direto do S3 com URL fresh
            try:
                resp = await context.request.get(fresh, timeout=60000)
                if not resp.ok:
                    body_snip = ""
                    try:
                        body_snip = (await resp.text())[:120]
                    except Exception:
                        pass
                    stats["errors"].append((stale_url[:100], f"HTTP {resp.status}: {body_snip}"))
                    done += 1
                    return
                blob = await resp.body()
                ct = resp.headers.get("content-type", "application/octet-stream")
                target = _target_path(assets_dir, stale_url, info, ct)
                target.write_bytes(blob)
                relpath = target.relative_to(assets_dir).as_posix()
                manifest[h] = {
                    "url_stale": stale_url,
                    "url_fresh": fresh,
                    "thread_uuid": info["thread_uuid"],
                    "source_type": info["source_type"],
                    "content_type": ct,
                    "size": len(blob),
                    "relpath": relpath,
                }
                stats["downloaded"] += 1
            except Exception as e:
                stats["errors"].append((stale_url[:100], str(e)[:200]))
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
