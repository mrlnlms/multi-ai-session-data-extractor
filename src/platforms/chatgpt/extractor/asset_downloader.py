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

from src.assets.incremental import AssetObservation, WebAssetCaptureSession
from src.assets.vault import AssetVault
from src.platforms.chatgpt.extractor.api_client import BASE_URL
from src.platforms.chatgpt.extractor.canvas_materializer import (
    parse_canvas_payload,
    replay_canvas_snapshots,
)

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
    if t == "code" or t.startswith("code/"):
        # Tenta inferir da extensao do nome (ex: "script.py" → "py")
        if "." in name:
            ext = name.rsplit(".", 1)[-1].lower()
            if len(ext) <= 6:
                return ext
        if "/" in t:
            language = t.split("/", 1)[1]
            return {"javascript": "js", "typescript": "ts", "python": "py"}.get(language, language)
        return "txt"
    if t == "html":
        return "html"
    return "txt"


def _legacy_canvas_payloads(raw_dir: Path) -> dict[tuple[str, float], dict[str, Any]]:
    """Load exact Canvas requests retained by legacy flattened snapshots."""
    data_root = next((parent for parent in raw_dir.resolve().parents if parent.name == "data"), None)
    if data_root is None:
        return {}
    snapshot_root = data_root / "external" / "chatgpt-extension-snapshot"
    recovered: dict[tuple[str, float], dict[str, Any]] = {}
    conflicts: set[tuple[str, float]] = set()
    for snapshot_path in sorted(snapshot_root.glob("**/chatgpt_all_conversations.json")):
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for conversation in snapshot.get("conversations") or []:
            if not isinstance(conversation, dict) or not conversation.get("id"):
                continue
            conv_id = str(conversation["id"])
            for message in conversation.get("messages") or []:
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                timestamp = message.get("timestamp")
                if not isinstance(timestamp, (int, float)):
                    continue
                payload = parse_canvas_payload(message.get("content"))
                if payload and ("content" in payload or "updates" in payload):
                    key = (conv_id, round(float(timestamp), 6))
                    if key in recovered and recovered[key] != payload:
                        conflicts.add(key)
                    elif key not in conflicts:
                        recovered[key] = payload
    for key in conflicts:
        recovered.pop(key, None)
    return recovered


def extract_canvases(
    raw_dir: Path,
    skip_existing: bool = True,
    *,
    asset_vault: AssetVault | None = None,
    account_id: str | None = None,
) -> dict:
    """Replay Canvas operations and materialize every reconstructable state."""
    raw_path = raw_dir / "chatgpt_raw.json"
    if not raw_path.exists():
        return {
            "extracted": 0, "skipped_existing": 0, "updates_patch": 0,
            "by_type": {}, "errors": [], "failed_upstream": 0,
            "unreconstructable": 0, "ambiguous": 0,
        }

    with open(raw_path) as f:
        data = json.load(f)

    out_root = raw_dir / "assets" / "canvases"
    out_root.mkdir(parents=True, exist_ok=True)
    legacy_payloads = _legacy_canvas_payloads(raw_dir)

    stats = {
        "extracted": 0, "skipped_existing": 0, "updates_patch": 0,
        "by_type": {}, "errors": [], "failed_upstream": 0,
        "unreconstructable": 0, "ambiguous": 0,
    }
    capture = WebAssetCaptureSession(
        asset_vault,
        source="chatgpt",
        account_id=account_id,
        evidence_path=raw_path,
        capture_method="web_asset_download:canvas",
    )

    for cid, conv in data.get("conversations", {}).items():
        fallbacks: dict[str, dict[str, Any]] = {}
        for node_id, node in (conv.get("mapping") or {}).items():
            message = (node or {}).get("message") or {}
            timestamp = message.get("create_time")
            if isinstance(timestamp, (int, float)):
                recovered = legacy_payloads.get((str(cid), round(float(timestamp), 6)))
                if recovered:
                    fallbacks[str(node_id)] = recovered
        snapshots, replay = replay_canvas_snapshots(conv, fallbacks)
        stats["failed_upstream"] += replay["failed_upstream"]
        stats["unreconstructable"] += replay["unreconstructable"]
        stats["ambiguous"] += replay["ambiguous"]
        stats["updates_patch"] += replay["updates"]
        for snapshot in snapshots:
            ext = _canvas_ext(snapshot.textdoc_type, snapshot.name)
            out_conv = out_root / cid
            out_conv.mkdir(parents=True, exist_ok=True)
            fname = (
                f"reconstructed__{_slug(snapshot.document_id, 34)}"
                f"__{_slug(snapshot.request_message_id, 36)}"
                f"__v{snapshot.version}_{_slug(snapshot.name, 40)}.{ext}"
            )
            out_path = out_conv / fname
            metadata = {
                "materialization": "canvas_replay_v1",
                "conv_id": cid,
                "textdoc_id": snapshot.document_id,
                "native_textdoc_id": snapshot.native_textdoc_id,
                "version": snapshot.version,
                "name": snapshot.name,
                "type": snapshot.textdoc_type,
                "message_id": snapshot.request_message_id,
                "response_message_id": snapshot.response_message_id,
                "create_time": snapshot.create_time,
                "content_size": len(snapshot.content),
                "evidence": snapshot.evidence,
                "asset_id": f"canvas:{snapshot.document_id}:{snapshot.request_message_id}",
            }
            meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
            expected_meta = json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True)
            if out_path.exists() or meta_path.exists():
                content_matches = (not out_path.exists() or (
                    out_path.is_file()
                    and out_path.read_text(encoding="utf-8") == snapshot.content
                ))
                metadata_matches = (not meta_path.exists() or (
                    meta_path.is_file()
                    and meta_path.read_text(encoding="utf-8") == expected_meta
                ))
                if content_matches and metadata_matches and out_path.exists() and meta_path.exists():
                    delivery_id = str(metadata["asset_id"])
                    capture.observe(AssetObservation(
                        delivery_id=delivery_id,
                        object_id=str(snapshot.document_id),
                        representation_kind="assistant_artifact",
                        payload=(out_path.read_bytes() if asset_vault is not None else None),
                        file_name=out_path.name,
                        mime_type="text/markdown" if ext == "md" else "text/plain",
                        upstream_locator=str(snapshot.native_textdoc_id or snapshot.document_id),
                    ))
                    stats["skipped_existing"] += 1
                    continue
                if not content_matches or not metadata_matches:
                    stats["errors"].append((fname, "existing Canvas snapshot differs"))
                    continue

            try:
                if not out_path.exists():
                    out_path.write_text(snapshot.content, encoding="utf-8")
                if not meta_path.exists():
                    meta_path.write_text(expected_meta, encoding="utf-8")
                delivery_id = str(metadata["asset_id"])
                capture.observe(AssetObservation(
                    delivery_id=delivery_id,
                    object_id=str(snapshot.document_id),
                    representation_kind="assistant_artifact",
                    payload=snapshot.content.encode(),
                    file_name=out_path.name,
                    mime_type="text/markdown" if ext == "md" else "text/plain",
                    upstream_locator=str(snapshot.native_textdoc_id or snapshot.document_id),
                ))
                stats["extracted"] += 1
                stats["by_type"][snapshot.textdoc_type] = (
                    stats["by_type"].get(snapshot.textdoc_type, 0) + 1
                )
            except Exception as e:
                stats["errors"].append((fname, str(e)[:100]))

    capture.finish(complete_discovery=False)
    return stats


def extract_deep_research(
    raw_dir: Path,
    skip_existing: bool = True,
    *,
    asset_vault: AssetVault | None = None,
    account_id: str | None = None,
) -> dict:
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
    capture = WebAssetCaptureSession(
        asset_vault,
        source="chatgpt",
        account_id=account_id,
        evidence_path=raw_path,
        capture_method="web_asset_download:deep_research",
    )

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
            delivery_id = f"deep-research:{task_id}"
            if skip_existing and out_path.exists():
                capture.observe(AssetObservation(
                    delivery_id=delivery_id,
                    object_id=str(task_id),
                    representation_kind="assistant_output",
                    payload=(out_path.read_bytes() if asset_vault is not None else None),
                    file_name=out_path.name,
                    mime_type="text/markdown",
                    upstream_locator=str(task_id),
                ))
                stats["skipped_existing"] += 1
                continue
            try:
                out_path.write_text(content, encoding="utf-8")
                capture.observe(AssetObservation(
                    delivery_id=delivery_id,
                    object_id=str(task_id),
                    representation_kind="assistant_output",
                    payload=content.encode(),
                    file_name=out_path.name,
                    mime_type="text/markdown",
                    upstream_locator=str(task_id),
                ))
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

    capture.finish(complete_discovery=False)
    return stats


async def run_asset_download(
    raw_dir: Path,
    only_conv_ids: list[str] | None = None,
    profile_name: str = "default",
    *,
    asset_vault: AssetVault | None = None,
    account_id: str | None = None,
    complete_discovery: bool = False,
) -> AssetReport:
    """Orquestrador: itera raw, baixa todos os image_asset_pointer via API."""
    from playwright.async_api import async_playwright
    from src.platforms.chatgpt.extractor.api_client import ChatGPTAPIClient
    from src.platforms.chatgpt.extractor.auth import get_profile_dir

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
    capture = WebAssetCaptureSession(
        asset_vault,
        source="chatgpt",
        account_id=account_id,
        evidence_path=raw_path,
        capture_method="web_asset_download:images",
    )

    async with async_playwright() as p:
        # Playwright so usado pra obter token de sessao — nao abre pagina
        context = await p.chromium.launch_persistent_context(
            str(get_profile_dir(profile_name)),
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
                    path = Path(result["path"])
                    capture.observe(AssetObservation(
                        delivery_id=fid,
                        object_id=fid,
                        representation_kind="delivery",
                        payload=path.read_bytes(),
                        file_name=result.get("filename") or path.name,
                        mime_type=result.get("content_type"),
                        upstream_locator=fid,
                    ))
                elif st == "skipped":
                    report.total_skipped_existing += 1
                    path = Path(result["path"])
                    capture.observe(AssetObservation(
                        delivery_id=fid,
                        object_id=fid,
                        representation_kind="delivery",
                        payload=(path.read_bytes() if asset_vault is not None else None),
                        file_name=path.name.split("__", 1)[-1],
                        upstream_locator=fid,
                    ))
                elif st == "failed":
                    report.total_failed += 1
                    capture.observe(AssetObservation(
                        delivery_id=fid,
                        object_id=fid,
                        representation_kind="delivery",
                        upstream_locator=fid,
                        failure_reason=str(result.get("reason") or "download failed"),
                    ))
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

    capture.finish(complete_discovery=complete_discovery)

    return report
