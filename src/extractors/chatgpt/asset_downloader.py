"""Download de assets do ChatGPT via API pura.

Fluxo:
  GET /backend-api/files/download/{file_id}
    → {status: "success", download_url: "https://..estuary/content?ts&sig..", file_name, ...}
  GET download_url
    → bytes

Funciona pra ambos formatos:
  - sediment://file_XXX (hex, moderno)
  - file-service://file-XXX (hífen, legado)

Descoberto via probe em 23/abr/2026. Substitui o approach Playwright anterior
(scroll + intercept), muito mais rapido e confiavel.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.extractors.chatgpt.api_client import BASE_URL

logger = logging.getLogger(__name__)

PER_REQUEST_SLEEP_SECONDS = 0.2  # throttle suave pra nao bombar API


@dataclass
class AssetReport:
    """Relatorio final de asset download."""
    total_expected: int = 0
    total_downloaded: int = 0
    total_skipped_existing: int = 0
    total_failed: int = 0
    convs_with_assets: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Asset download (API-based):\n"
            f"  Convs com assets: {self.convs_with_assets}\n"
            f"  Expected: {self.total_expected}\n"
            f"  Downloaded: {self.total_downloaded}\n"
            f"  Skipped (ja existiam): {self.total_skipped_existing}\n"
            f"  Failed: {self.total_failed}\n"
            f"  Failure examples: {len(self.failures)}"
        )


def collect_image_assets_from_raw(raw_path: Path) -> dict[str, list[dict]]:
    """Varre raw e mapeia conv_id -> [{file_id, size_bytes, ...}].

    Inclui AMBOS formatos: sediment://file_XXX e file-service://file-XXX.
    """
    with open(raw_path) as f:
        raw = json.load(f)
    result: dict[str, list[dict]] = {}
    for cid, conv in raw.get("conversations", {}).items():
        images = []
        for node in (conv.get("mapping") or {}).values():
            msg = node.get("message") or {}
            for part in (msg.get("content") or {}).get("parts", []):
                if isinstance(part, dict) and part.get("content_type") == "image_asset_pointer":
                    ptr = part.get("asset_pointer", "")
                    fid = ptr.replace("sediment://", "").replace("file-service://", "")
                    if fid:
                        images.append({
                            "file_id": fid,
                            "format": "sediment" if ptr.startswith("sediment://") else "file-service",
                            "size_bytes": part.get("size_bytes"),
                            "width": part.get("width"),
                            "height": part.get("height"),
                        })
        if images:
            seen = set()
            deduped = []
            for img in images:
                if img["file_id"] not in seen:
                    seen.add(img["file_id"])
                    deduped.append(img)
            result[cid] = deduped
    return result


def _extension_from_content_type(ct: str) -> str:
    ct = (ct or "").split(";")[0].strip()
    return {
        "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
        "image/webp": "webp", "image/gif": "gif", "image/svg+xml": "svg",
        "application/pdf": "pdf",
    }.get(ct, "bin")


def _filename_from_content_disposition(cd: str) -> str | None:
    if not cd:
        return None
    if "filename*=" in cd:
        try:
            raw = cd.split("filename*=")[1].split(";")[0].strip()
            if "''" in raw:
                raw = raw.split("''", 1)[1]
            from urllib.parse import unquote
            return unquote(raw)
        except Exception:
            pass
    if 'filename="' in cd:
        return cd.split('filename="')[1].split('"')[0]
    return None


async def fetch_download_url(request_context, token: str, file_id: str) -> dict | None:
    """GET /files/download/{id} — retorna {download_url, file_name, ...} ou None se erro."""
    url = f"{BASE_URL}/files/download/{file_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = await request_context.get(url, headers=headers)
        if not r.ok:
            body = (await r.text())[:200]
            logger.debug(f"  download url fetch {file_id}: HTTP {r.status}: {body}")
            return None
        data = await r.json()
        if data.get("status") != "success" or not data.get("download_url"):
            logger.debug(f"  {file_id}: status={data.get('status')} error={data.get('error_code')}")
            return None
        return data
    except Exception as exc:
        logger.debug(f"  {file_id}: fetch url exc: {exc}")
        return None


async def download_one_asset(
    request_context,
    token: str,
    file_id: str,
    out_dir: Path,
    suggested_name: str | None = None,
) -> dict:
    """Baixa 1 asset via API. Retorna dict com status + metadata.

    Skip se arquivo com file_id prefix ja existe.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = list(out_dir.glob(f"{file_id}__*"))
    if existing:
        return {"file_id": file_id, "status": "skipped", "path": str(existing[0])}

    # Passo 1: obtem download_url
    meta = await fetch_download_url(request_context, token, file_id)
    if not meta:
        return {"file_id": file_id, "status": "failed", "reason": "no_download_url"}

    download_url = meta["download_url"]
    file_name = meta.get("file_name") or suggested_name

    # Passo 2: baixa bytes
    try:
        r = await request_context.get(download_url, headers={"Authorization": f"Bearer {token}"})
        if not r.ok:
            return {"file_id": file_id, "status": "failed", "reason": f"download HTTP {r.status}"}
        body_bytes = await r.body()
        ct = r.headers.get("content-type", "")
        cd = r.headers.get("content-disposition", "")
        filename = (
            _filename_from_content_disposition(cd)
            or file_name
            or f"{file_id}.{_extension_from_content_type(ct)}"
        )
        # Prefixa file_id pra evitar colisao de nomes
        out_path = out_dir / f"{file_id}__{filename}"
        out_path.write_bytes(body_bytes)
        return {
            "file_id": file_id,
            "status": "downloaded",
            "filename": filename,
            "size": len(body_bytes),
            "content_type": ct,
            "path": str(out_path),
        }
    except Exception as exc:
        return {"file_id": file_id, "status": "failed", "reason": str(exc)}


def _slug(s: str, max_len: int = 60) -> str:
    """Slugify pra filename."""
    import re
    s = re.sub(r'[^\w\-. ]', '', s or '')
    s = re.sub(r'\s+', '_', s.strip())
    return (s or 'untitled')[:max_len]


def _canvas_ext(textdoc_type: str, name: str = "") -> str:
    """Deriva extensao do Canvas a partir de textdoc_type + nome."""
    t = (textdoc_type or "").lower()
    if t == "document":
        return "md"
    if t == "code":
        # Tenta inferir da extensao do nome (ex: "script.py" → "py")
        if "." in name:
            ext = name.rsplit(".", 1)[-1].lower()
            if len(ext) <= 6:
                return ext
        return "txt"
    if t == "html":
        return "html"
    return "txt"


def extract_canvases(raw_dir: Path, skip_existing: bool = True) -> dict:
    """Extrai Canvas/textdoc do raw ChatGPT.

    Varre msgs com recipient='canmore.*' (create/update/comment). Part[0] e JSON com
    {name, type, content}. Salva cada versao como arquivo separado.

    Output: assets/canvases/{conv_id}/{textdoc_id}_v{N}_{name}.{ext} + meta.json
    """
    raw_path = raw_dir / "chatgpt_raw.json"
    if not raw_path.exists():
        return {"extracted": 0, "skipped_existing": 0, "updates_patch": 0, "by_type": {}, "errors": []}

    with open(raw_path) as f:
        data = json.load(f)

    out_root = raw_dir / "assets" / "canvases"
    out_root.mkdir(parents=True, exist_ok=True)

    stats = {"extracted": 0, "skipped_existing": 0, "updates_patch": 0, "by_type": {}, "errors": []}
    # Conta versoes por (conv, textdoc_id)
    version_counter: dict[tuple[str, str], int] = {}

    for cid, conv in data.get("conversations", {}).items():
        # Ordena nodes por create_time pra numerar versoes na ordem
        nodes = []
        for nid, n in (conv.get("mapping") or {}).items():
            m = (n or {}).get("message") or {}
            if not m: continue
            recipient = m.get("recipient") or ""
            if not recipient.startswith("canmore."):
                continue
            if (m.get("author") or {}).get("role") != "assistant":
                continue
            ct = (m.get("create_time") or 0) or 0
            nodes.append((ct, nid, m, recipient))
        nodes.sort(key=lambda x: x[0])

        for ct, nid, m, recipient in nodes:
            parts = (m.get("content") or {}).get("parts") or []
            if not parts or not isinstance(parts[0], str):
                continue
            raw_payload = parts[0]
            try:
                payload = json.loads(raw_payload)
            except Exception as e:
                stats["errors"].append((cid[:8], f"{recipient}: json parse: {str(e)[:80]}"))
                continue

            textdoc_id = payload.get("textdoc_id") or payload.get("id") or "unknown"
            name = payload.get("name") or "untitled"
            td_type = payload.get("type") or "document"
            content = payload.get("content")

            # update_textdoc usa pattern/replacement (patch, sem content full)
            # Guarda como .patch.json pra historico
            if recipient == "canmore.update_textdoc" and content is None:
                updates = payload.get("updates") or []
                if not updates:
                    continue
                out_conv = out_root / cid
                out_conv.mkdir(parents=True, exist_ok=True)
                patch_fname = f"{textdoc_id}__patch_{nid[:8]}.json"
                out_path = out_conv / patch_fname
                if skip_existing and out_path.exists():
                    stats["skipped_existing"] += 1
                    continue
                out_path.write_text(json.dumps({
                    "recipient": recipient,
                    "textdoc_id": textdoc_id,
                    "updates": updates,
                    "message_id": nid,
                    "create_time": ct,
                }, indent=2, ensure_ascii=False))
                stats["updates_patch"] += 1
                continue

            if content is None:
                continue

            key = (cid, textdoc_id)
            version_counter[key] = version_counter.get(key, 0) + 1
            v = version_counter[key]

            ext = _canvas_ext(td_type, name)
            out_conv = out_root / cid
            out_conv.mkdir(parents=True, exist_ok=True)
            fname = f"{_slug(textdoc_id, 30)}_v{v}_{_slug(name, 40)}.{ext}"
            out_path = out_conv / fname
            if skip_existing and out_path.exists():
                stats["skipped_existing"] += 1
                continue

            try:
                out_path.write_text(content, encoding="utf-8")
                stats["extracted"] += 1
                stats["by_type"][td_type] = stats["by_type"].get(td_type, 0) + 1
                meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
                meta_path.write_text(json.dumps({
                    "conv_id": cid,
                    "textdoc_id": textdoc_id,
                    "version": v,
                    "name": name,
                    "type": td_type,
                    "recipient": recipient,
                    "message_id": nid,
                    "create_time": ct,
                    "content_size": len(content),
                }, indent=2, ensure_ascii=False))
            except Exception as e:
                stats["errors"].append((fname, str(e)[:100]))

    return stats


def extract_deep_research(raw_dir: Path, skip_existing: bool = True) -> dict:
    """Extrai relatorios de Deep Research do raw ChatGPT.

    Varre msgs do assistant com metadata.is_async_task_result_message=True.
    Salva part[0] (markdown) + citations + content_references.

    Output: assets/deep_research/{conv_id}/{async_task_id}_{slug_title}.md + meta.json
    """
    raw_path = raw_dir / "chatgpt_raw.json"
    if not raw_path.exists():
        return {"extracted": 0, "skipped_existing": 0, "errors": []}

    with open(raw_path) as f:
        data = json.load(f)

    out_root = raw_dir / "assets" / "deep_research"
    out_root.mkdir(parents=True, exist_ok=True)

    stats = {"extracted": 0, "skipped_existing": 0, "errors": []}

    for cid, conv in data.get("conversations", {}).items():
        for nid, n in (conv.get("mapping") or {}).items():
            m = (n or {}).get("message") or {}
            if not m: continue
            md = m.get("metadata") or {}
            if not md.get("is_async_task_result_message"):
                continue
            parts = (m.get("content") or {}).get("parts") or []
            if not parts or not isinstance(parts[0], str):
                continue
            content = parts[0]
            if not content.strip():
                continue

            task_id = md.get("async_task_id") or nid[:8]
            title = md.get("async_task_title") or conv.get("title") or "research_report"

            out_conv = out_root / cid
            out_conv.mkdir(parents=True, exist_ok=True)
            fname = f"{_slug(task_id, 30)}_{_slug(title, 60)}.md"
            out_path = out_conv / fname
            if skip_existing and out_path.exists():
                stats["skipped_existing"] += 1
                continue
            try:
                out_path.write_text(content, encoding="utf-8")
                stats["extracted"] += 1
                meta_path = out_path.with_suffix(".md.meta.json")
                meta_path.write_text(json.dumps({
                    "conv_id": cid,
                    "async_task_id": task_id,
                    "title": title,
                    "message_id": nid,
                    "create_time": m.get("create_time"),
                    "content_size": len(content),
                    "citations": md.get("citations", []),
                    "content_references": md.get("content_references", []),
                    "model_slug": md.get("model_slug"),
                }, indent=2, ensure_ascii=False))
            except Exception as e:
                stats["errors"].append((fname, str(e)[:100]))

    return stats


async def run_asset_download(
    raw_dir: Path,
    only_conv_ids: list[str] | None = None,
) -> AssetReport:
    """Orquestrador: itera raw, baixa todos os image_asset_pointer via API."""
    from playwright.async_api import async_playwright
    from src.extractors.chatgpt.api_client import ChatGPTAPIClient
    from src.extractors.chatgpt.auth import get_profile_dir

    raw_path = raw_dir / "chatgpt_raw.json"
    assets_root = raw_dir / "assets"
    images_root = assets_root / "images"

    logger.info(f"Mapeando image_asset_pointers em {raw_path}")
    conv_images = collect_image_assets_from_raw(raw_path)
    total_convs = len(conv_images)
    total_images = sum(len(v) for v in conv_images.values())
    logger.info(f"  {total_convs} convs com assets, total {total_images} asset_pointers")

    if only_conv_ids:
        conv_images = {k: v for k, v in conv_images.items() if k in set(only_conv_ids)}
        logger.info(f"  Filtrado pra {len(conv_images)} convs (only_conv_ids)")

    report = AssetReport(
        total_expected=sum(len(v) for v in conv_images.values()),
        convs_with_assets=len(conv_images),
    )

    async with async_playwright() as p:
        # Playwright so usado pra obter token de sessao — nao abre pagina
        context = await p.chromium.launch_persistent_context(
            str(get_profile_dir()),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        client = ChatGPTAPIClient(context.request)
        token = await client._get_token()
        logger.info("Token obtido, iniciando downloads via API")

        for i, (conv_id, images) in enumerate(conv_images.items(), 1):
            logger.info(f"[{i}/{len(conv_images)}] conv {conv_id} ({len(images)} assets)")
            conv_out_dir = images_root / conv_id

            for img in images:
                fid = img["file_id"]
                result = await download_one_asset(
                    context.request, token, fid, conv_out_dir
                )
                st = result["status"]
                if st == "downloaded":
                    report.total_downloaded += 1
                elif st == "skipped":
                    report.total_skipped_existing += 1
                elif st == "failed":
                    report.total_failed += 1
                    if len(report.failures) < 50:
                        report.failures.append({
                            "conv_id": conv_id,
                            "file_id": fid,
                            "reason": result.get("reason"),
                            "format": img.get("format"),
                        })
                await asyncio.sleep(PER_REQUEST_SLEEP_SECONDS)

            logger.info(
                f"  downloaded={report.total_downloaded} "
                f"skipped={report.total_skipped_existing} "
                f"failed={report.total_failed}"
            )

        await context.close()

    # Salva report
    report_path = assets_root / "asset_download_report.json"
    assets_root.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "total_expected": report.total_expected,
        "total_downloaded": report.total_downloaded,
        "total_skipped_existing": report.total_skipped_existing,
        "total_failed": report.total_failed,
        "convs_with_assets": report.convs_with_assets,
        "failures": report.failures,
    }, indent=2, ensure_ascii=False))

    return report
