"""Asset downloader DeepSeek: user uploads via /api/v0/file/preview.

DeepSeek usa Huawei Cloud OBS como storage. Fluxo:
  1. GET /api/v0/file/preview?file_id=X&chat_session_id=Y&message_id=Z
     Retorna {biz_data: {url: "https://deepseek-api-files.obs.cn-east-3.myhuaweicloud.com/..."}}
     (URL presigned, Expires=~10min)
  2. GET {presigned_url} — baixa binario direto do OBS

DeepSeek so gera texto — nao ha assets gerados pelo modelo. So uploads do user.
"""

import asyncio
import hashlib
import json
import re
from pathlib import Path

from playwright.async_api import BrowserContext, Page


API_BASE = "https://chat.deepseek.com/api/v0"


def _collect_files(raw_dir: Path) -> list[dict]:
    """Retorna lista de {file_id, file_name, conv_id, message_id, size}."""
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists():
        return []
    entries: list[dict] = []
    for jp in conv_dir.glob("*.json"):
        try:
            with open(jp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        cs = data.get("chat_session", {}) or {}
        conv_id = cs.get("id") or jp.stem
        for msg in data.get("chat_messages", []) or []:
            mid = msg.get("message_id")
            for fmeta in msg.get("files") or []:
                fid = fmeta.get("id")
                if not fid:
                    continue
                entries.append({
                    "file_id": fid,
                    "file_name": fmeta.get("file_name") or fid,
                    "conv_id": conv_id,
                    "message_id": mid,
                    "size_hint": fmeta.get("file_size"),
                    "status": fmeta.get("status"),
                })
    return entries


def _safe(name: str) -> str:
    return re.sub(r'[<>:"|?*\x00-\x1f/\\]', "_", name)[:200]


async def _get_presigned_url(page: Page, token: str, file_id: str, conv_id: str, message_id: int) -> str | None:
    """Chama /api/v0/file/preview e retorna a URL presigned ou None."""
    path = f"{API_BASE}/file/preview?file_id={file_id}&chat_session_id={conv_id}&message_id={message_id}"
    script = """async ({path, token}) => {
        const res = await fetch(path, {
            headers: {
                'authorization': 'Bearer ' + token,
                'x-client-locale': 'en_US',
                'x-app-version': '20241129.1',
                'x-client-version': '1.8.0',
            }
        });
        const txt = await res.text();
        return {status: res.status, body: txt};
    }"""
    r = await page.evaluate(script, {"path": path, "token": token})
    if r["status"] != 200:
        return None
    try:
        parsed = json.loads(r["body"])
        if parsed.get("code") != 0:
            return None
        bd = parsed.get("data", {}).get("biz_data", {})
        if not bd:
            return None
        return bd.get("url")
    except Exception:
        return None


async def download_assets(
    context: BrowserContext,
    page: Page,
    token: str,
    raw_dir: Path,
    concurrency: int = 3,
    skip_existing: bool = True,
) -> dict:
    entries = _collect_files(raw_dir)
    print(f"Encontrados {len(entries)} file references")

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
    total = len(entries)

    async def _one(e: dict):
        nonlocal done
        fid = e["file_id"]
        if skip_existing and fid in manifest:
            existing = assets_dir / manifest[fid].get("relpath", "")
            if existing.exists():
                stats["skipped"] += 1
                done += 1
                return
        async with sem:
            # 1) Pega presigned URL fresh
            try:
                url = await _get_presigned_url(page, token, fid, e["conv_id"], e["message_id"])
            except Exception as ex:
                stats["errors"].append((fid, f"preview: {str(ex)[:150]}"))
                done += 1
                return
            if not url:
                stats["errors"].append((fid, "no presigned url (maybe file expired/deleted upstream)"))
                done += 1
                return
            # 2) Download direto do OBS
            try:
                resp = await context.request.get(url, timeout=60000)
                if not resp.ok:
                    stats["errors"].append((fid, f"HTTP {resp.status}"))
                    done += 1
                    return
                blob = await resp.body()
                ct = resp.headers.get("content-type", "application/octet-stream")
                folder = assets_dir / e["conv_id"]
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / _safe(e["file_name"])
                target.write_bytes(blob)
                relpath = target.relative_to(assets_dir).as_posix()
                manifest[fid] = {
                    "file_id": fid,
                    "file_name": e["file_name"],
                    "conv_id": e["conv_id"],
                    "message_id": e["message_id"],
                    "content_type": ct,
                    "size": len(blob),
                    "relpath": relpath,
                }
                stats["downloaded"] += 1
            except Exception as ex:
                stats["errors"].append((fid, f"download: {str(ex)[:150]}"))
            done += 1
            if done % 10 == 0:
                print(f"  [{done}/{total}] dl={stats['downloaded']} "
                      f"skip={stats['skipped']} err={len(stats['errors'])}")

    await asyncio.gather(*(_one(e) for e in entries))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"  [{done}/{total}] dl={stats['downloaded']} "
          f"skip={stats['skipped']} err={len(stats['errors'])} (final)")
    return stats
