"""Asset downloader Gemini: baixa imagens (lh3.googleusercontent.com) das convs.

URLs sao presigned — baixar logo apos fetch. Nome do arquivo via hash do path
pra dedup (Gemini nao expoe file_uuid estavel nas imagens geradas).
"""

import asyncio
import hashlib
import json
import mimetypes
from pathlib import Path

from src.assets.incremental import (
    AssetObservation,
    WebAssetCaptureSession,
    commit_web_asset_capture,
)
from src.assets.vault import AssetVault
from src.platforms.gemini.extractor.api_client import GeminiAPIClient, extract_image_urls


def _filename_from_url(url: str, content_type: str) -> str:
    """Gera nome deterministico a partir do hash da URL + ext do content-type."""
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
    return f"{h}{ext}"


async def download_assets(
    client: GeminiAPIClient,
    raw_dir: Path,
    concurrency: int = 5,
    skip_existing: bool = True,
    *,
    asset_vault: AssetVault | None = None,
    account_id: str | None = None,
    complete_discovery: bool = True,
) -> dict:
    """Varre conversations/*.json, extrai URLs, baixa binarios."""
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists():
        commit_web_asset_capture(
            asset_vault,
            source="gemini",
            account_id=account_id,
            observations=(),
            complete_discovery=complete_discovery,
            evidence_path=conv_dir,
        )
        return {"downloaded": 0, "skipped": 0, "errors": []}

    # Coleta URLs unicos (conv_id, url)
    all_urls: dict[str, str] = {}  # url → conv_id (origem, referencia)
    for jp in conv_dir.glob("*.json"):
        try:
            with open(jp, encoding="utf-8") as f:
                conv = json.load(f)
        except Exception:
            continue
        urls = extract_image_urls(conv.get("raw"))
        cid = conv.get("uuid", jp.stem)
        for u in urls:
            if u not in all_urls:
                all_urls[u] = cid

    print(f"Encontradas {len(all_urls)} URLs unicas de imagem")

    assets_dir = raw_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Manifest: hash → {url, conv_id, content_type, size}
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
    total = len(all_urls)
    capture = WebAssetCaptureSession(
        asset_vault,
        source="gemini",
        account_id=account_id,
        evidence_path=raw_dir,
        capture_method="web_asset_download",
        staging_root=assets_dir,
    )

    async def _one(url: str, conv_id: str):
        nonlocal done
        h = hashlib.sha1(url.encode()).hexdigest()[:16]
        # Se ja baixou e skip_existing, pula
        async with sem:
            if skip_existing and h in manifest:
                existing = assets_dir / manifest[h].get("filename", "")
                if existing.exists():
                    info = manifest[h]
                    payload = existing.read_bytes() if asset_vault is not None else None
                    delivery_id = hashlib.sha256(payload).hexdigest() if payload is not None else h
                    capture.observe(AssetObservation(
                        delivery_id=delivery_id,
                        object_id=delivery_id,
                        representation_kind="delivery",
                        payload=payload,
                        file_name=existing.name,
                        mime_type=info.get("content_type"),
                        upstream_locator=url,
                    ))
                    stats["skipped"] += 1
                    done += 1
                    return
            try:
                resp = await client.context.request.get(url)
                if not resp.ok:
                    stats["errors"].append((url[:80], f"HTTP {resp.status}"))
                    delivery_id = "manifest:" + hashlib.sha256(url.encode()).hexdigest()
                    capture.observe(AssetObservation(
                        delivery_id=delivery_id,
                        object_id=delivery_id,
                        representation_kind="delivery",
                        upstream_locator=url,
                        failure_reason=f"HTTP {resp.status}",
                    ))
                    done += 1
                    return
                blob = await resp.body()
                ct = resp.headers.get("content-type", "application/octet-stream")
                filename = _filename_from_url(url, ct)
                (assets_dir / filename).write_bytes(blob)
                delivery_id = hashlib.sha256(blob).hexdigest()
                capture.observe(AssetObservation(
                    delivery_id=delivery_id,
                    object_id=delivery_id,
                    representation_kind="delivery",
                    payload=blob,
                    file_name=filename,
                    mime_type=ct,
                    upstream_locator=url,
                ))
                manifest[h] = {
                    "url": url,
                    "conv_id": conv_id,
                    "content_type": ct,
                    "size": len(blob),
                    "filename": filename,
                }
                stats["downloaded"] += 1
            except Exception as e:
                stats["errors"].append((url[:80], str(e)[:150]))
                delivery_id = "manifest:" + hashlib.sha256(url.encode()).hexdigest()
                capture.observe(AssetObservation(
                    delivery_id=delivery_id,
                    object_id=delivery_id,
                    representation_kind="delivery",
                    upstream_locator=url,
                    failure_reason=str(e)[:150],
                ))
            done += 1
            if done % 20 == 0:
                print(
                    f"  [{done}/{total}] dl={stats['downloaded']} "
                    f"skip={stats['skipped']} err={len(stats['errors'])}"
                )

    await asyncio.gather(*(_one(u, c) for u, c in all_urls.items()))

    # Salva manifest
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    capture.finish(complete_discovery=complete_discovery)
    print(
        f"  [{done}/{total}] dl={stats['downloaded']} "
        f"skip={stats['skipped']} err={len(stats['errors'])} (final)"
    )
    return stats


def _walk_long_strings(raw, min_len: int = 2500):
    """Gera (path, string) pra strings longas no raw aninhado."""
    def _walk(x, path):
        if isinstance(x, str) and len(x) >= min_len:
            yield (path, x)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                yield from _walk(v, f"{path}[{i}]")
        elif isinstance(x, dict):
            for k, v in x.items():
                yield from _walk(v, f"{path}.{k}")
    yield from _walk(raw, "")


def _is_markdown_report(s: str) -> bool:
    """Heuristica: comeca com cabecalho markdown (## ou #) nos primeiros 300 chars."""
    head = s[:300].lstrip()
    if head.startswith("## ") or head.startswith("# "):
        return True
    # Ou tem headers no inicio
    import re
    return bool(re.search(r'\n##?\s+\w', head))


def extract_deep_research(
    raw_dir: Path,
    skip_existing: bool = True,
    *,
    asset_vault: AssetVault | None = None,
    account_id: str | None = None,
) -> dict:
    """Extrai relatorios Deep Research de conversations/*.json.

    Heuristica: strings >=2500 chars no raw aninhado que parecam markdown
    (header '##' ou '#' nos primeiros 300 chars). Essas sao relatorios do modelo.

    Output: assets/deep_research/{conv_id}/{hash}.md + meta.json
    """
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists():
        return {"extracted": 0, "skipped_existing": 0, "errors": []}

    out_root = raw_dir / "assets" / "deep_research"
    out_root.mkdir(parents=True, exist_ok=True)

    stats = {"extracted": 0, "skipped_existing": 0, "errors": []}
    capture = WebAssetCaptureSession(
        asset_vault,
        source="gemini",
        account_id=account_id,
        evidence_path=conv_dir,
        capture_method="web_asset_download:deep_research",
        staging_root=out_root,
    )

    for jp in sorted(conv_dir.glob("*.json")):
        try:
            with open(jp, encoding="utf-8") as f:
                conv = json.load(f)
        except Exception as e:
            stats["errors"].append((jp.name, f"load: {str(e)[:80]}"))
            continue

        cid = conv.get("uuid") or jp.stem
        raw = conv.get("raw")
        if not raw:
            continue

        reports = []
        for path, s in _walk_long_strings(raw, min_len=2500):
            if not _is_markdown_report(s):
                continue
            reports.append((path, s))

        if not reports:
            continue

        out_conv = out_root / cid
        out_conv.mkdir(parents=True, exist_ok=True)
        for idx, (path, content) in enumerate(reports):
            # Hash do conteudo pra dedup
            h = hashlib.sha1(content.encode()).hexdigest()[:10]
            fname = f"report_{idx:02d}_{h}.md"
            out_path = out_conv / fname
            payload = content.encode()
            delivery_id = hashlib.sha256(payload).hexdigest()
            if skip_existing and out_path.exists():
                capture.observe(AssetObservation(
                    delivery_id=delivery_id,
                    object_id=delivery_id,
                    representation_kind="assistant_output",
                    payload=(out_path.read_bytes() if asset_vault is not None else None),
                    file_name=out_path.name,
                    mime_type="text/markdown",
                    upstream_locator=f"{cid}:{path}",
                ))
                stats["skipped_existing"] += 1
                continue
            try:
                out_path.write_text(content, encoding="utf-8")
                capture.observe(AssetObservation(
                    delivery_id=delivery_id,
                    object_id=delivery_id,
                    representation_kind="assistant_output",
                    payload=payload,
                    file_name=out_path.name,
                    mime_type="text/markdown",
                    upstream_locator=f"{cid}:{path}",
                ))
                stats["extracted"] += 1
                meta_path = out_path.with_suffix(".md.meta.json")
                # Tenta extrair titulo da primeira linha
                first_line = content.lstrip().split("\n", 1)[0].lstrip("#").strip()
                meta_path.write_text(json.dumps({
                    "conv_id": cid,
                    "source_path": path,
                    "title": first_line[:200],
                    "content_size": len(content),
                }, indent=2, ensure_ascii=False))
            except Exception as e:
                stats["errors"].append((fname, str(e)[:100]))

    capture.finish(complete_discovery=False)
    return stats
