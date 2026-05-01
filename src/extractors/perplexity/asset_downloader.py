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

    # 2) threads-index.featured_images (top-level)
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

    # 3) entries.featured_images (por entry — alguns threads tem aqui)
    if threads_dir.exists():
        for jp in threads_dir.glob("*.json"):
            try:
                with open(jp, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            tuuid = jp.stem
            for entry in data.get("entries", []) or []:
                for fi in entry.get("featured_images") or []:
                    u = fi if isinstance(fi, str) else (fi.get("url") if isinstance(fi, dict) else None)
                    if u and u.startswith("http") and _is_own_asset(u):
                        urls.setdefault(u, {
                            "thread_uuid": tuuid,
                            "source_type": "featured_image_entry",
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


async def _refresh_url_via_api(page, stale_url: str, thread_id: str | None = None) -> str | None:
    """Chama /rest/file-repository/download-attachment pra pegar URL fresh.

    Schema atualizado em 2026-05-01: endpoint agora exige campo `thread_id`
    no body alem da URL. Sem thread_id retorna 422 missing field.
    """
    payloads = []
    if thread_id:
        payloads.append(("/rest/file-repository/download-attachment", {"url": stale_url, "thread_id": thread_id}, "file_url"))
        payloads.append(("/rest/file-repository/download", {"file_url": stale_url, "thread_id": thread_id}, "file_url"))
    # Fallback sem thread_id
    payloads.append(("/rest/file-repository/download-attachment", {"url": stale_url}, "file_url"))
    payloads.append(("/rest/file-repository/download", {"file_url": stale_url}, "file_url"))

    for ep, payload, field_out in payloads:
        result = await page.evaluate("""async ({ep, payload}) => {
            const res = await fetch(ep + '?version=2.18&source=default', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const txt = await res.text();
            return {status: res.status, body: txt};
        }""", {"ep": ep, "payload": payload})
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

    # Pasta separada pra nao conflitar com artifacts (assets/ usado por
    # artifact_downloader.py). Aqui sao uploads do user EM threads.
    assets_dir = raw_dir / "thread_attachments"
    assets_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = raw_dir / "thread_attachments_manifest.json"
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

    async def _try_download(url: str) -> tuple[bytes | None, str, str]:
        """Tenta baixar 1 URL. Retorna (bytes, content_type, error_str)."""
        try:
            resp = await context.request.get(url, timeout=60000)
            if not resp.ok:
                body = ""
                try: body = (await resp.text())[:120]
                except Exception: pass
                return None, "", f"HTTP {resp.status}: {body}"
            blob = await resp.body()
            ct = resp.headers.get("content-type", "application/octet-stream")
            return blob, ct, ""
        except Exception as e:
            return None, "", str(e)[:200]

    async def _one(stale_url: str, info: dict):
        nonlocal done
        h = hashlib.sha1(stale_url.encode()).hexdigest()[:16]
        async with sem:
            if skip_existing and h in manifest:
                # Skip se ja baixado E arquivo existe
                relpath = manifest[h].get("relpath")
                if relpath and (assets_dir / relpath).exists():
                    stats["skipped"] += 1
                    done += 1
                    return
                # Skip se ja tentou e falhou por upstream deletion (idempotencia)
                if manifest[h].get("status") == "failed_upstream_deleted":
                    stats["skipped"] += 1
                    done += 1
                    return

            # 1) Tenta URL original direto (pode estar valida ainda)
            blob, ct, err = await _try_download(stale_url)
            url_used = stale_url
            url_fresh: str | None = None

            # 2) Falhou? Tenta refresh via /rest/file-repository/* (URL S3 expirou)
            if blob is None:
                url_fresh = await _refresh_url_via_api(page, stale_url, thread_id=info.get("thread_uuid"))
                if url_fresh:
                    blob, ct, err = await _try_download(url_fresh)
                    url_used = url_fresh
                else:
                    err = f"original failed ({err}), refresh returned no fresh URL"

            if blob is None:
                # Preserva entry no manifest mesmo com erro — distingue "ja tentei e falhou"
                # vs "nunca tentei". Permite skip futuro em re-runs idempotentes.
                manifest[h] = {
                    "url_stale": stale_url,
                    "url_fresh": url_fresh,
                    "thread_uuid": info["thread_uuid"],
                    "source_type": info["source_type"],
                    "status": "failed_upstream_deleted" if "404" in err or "NoSuchKey" in err else "failed",
                    "error": err[:200],
                }
                stats["errors"].append((stale_url[:100], err))
                done += 1
                return

            try:
                target = _target_path(assets_dir, stale_url, info, ct)
                target.write_bytes(blob)
                relpath = target.relative_to(assets_dir).as_posix()
                manifest[h] = {
                    "url_stale": stale_url,
                    "url_fresh": url_fresh,
                    "thread_uuid": info["thread_uuid"],
                    "source_type": info["source_type"],
                    "content_type": ct,
                    "size": len(blob),
                    "relpath": relpath,
                }
                stats["downloaded"] += 1
            except Exception as e:
                stats["errors"].append((stale_url[:100], f"write failed: {str(e)[:200]}"))
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
