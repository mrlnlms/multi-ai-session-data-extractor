"""Asset downloader: baixa binarios de files (imagens) em batch.

Varre JSONs em conversations/ e projects/ pra coletar file_uuids,
baixa preview (e opcionalmente thumbnail) de cada um. Skip-existing por default.

Tambem extrai artifacts (code/markdown/html/react/mermaid/svg) de tool_use blocks
como arquivos separados em assets/artifacts/.
"""

import asyncio
import json
from pathlib import Path

from src.extractors.claude_ai.api_client import ClaudeAPIClient


# MIME type Anthropic -> extensao de arquivo
ARTIFACT_TYPE_EXT = {
    "text/markdown": "md",
    "text/html": "html",
    "text/plain": "txt",
    "text/css": "css",
    "text/javascript": "js",
    "application/vnd.ant.react": "tsx",
    "application/vnd.ant.mermaid": "mmd",
    "application/vnd.ant.code": None,  # usa language
    "image/svg+xml": "svg",
    "application/json": "json",
}

# language -> extensao (pra application/vnd.ant.code)
LANG_EXT = {
    "python": "py", "typescript": "ts", "javascript": "js", "tsx": "tsx",
    "jsx": "jsx", "bash": "sh", "yaml": "yaml", "json": "json",
    "html": "html", "css": "css", "sql": "sql", "go": "go",
    "rust": "rs", "java": "java", "kotlin": "kt", "swift": "swift",
    "ruby": "rb", "php": "php", "c": "c", "cpp": "cpp",
    "csharp": "cs", "r": "R", "scala": "scala", "lua": "lua",
    "perl": "pl", "markdown": "md", "dockerfile": "Dockerfile",
    "makefile": "Makefile", "text": "txt", "xml": "xml",
}


# file_kind → (variants_to_download, is_downloadable)
# - image: /preview (principal, maior) + /thumbnail (opcional)
# - document (PDFs): so /thumbnail (capa renderizada — binario nao e exposto)
# - blob (.txt colados): nao baixavel (texto ja vem em extracted_content/msg inline)
KIND_VARIANTS: dict[str, list[str]] = {
    "image": ["preview"],  # thumbnail opcional via flag
    "document": ["thumbnail"],  # so a capa
    "blob": [],  # nao baixavel
}


def _scan_file_uuids(raw_dir: Path) -> list[tuple[str, str, str]]:
    """Varre conversations/ e projects/ em raw_dir, coleta (file_uuid, file_kind, file_name).

    Dedup por file_uuid. Inclui blobs (nao-baixaveis) na lista so pra contagem.
    """
    seen: dict[str, tuple[str, str]] = {}

    # Conversations: msg.files[].file_uuid + msg.files[].file_kind
    conv_dir = raw_dir / "conversations"
    if conv_dir.exists():
        for jp in conv_dir.glob("*.json"):
            try:
                with open(jp, encoding="utf-8") as f:
                    conv = json.load(f)
            except Exception:
                continue
            for m in conv.get("chat_messages", []):
                for fl in m.get("files", []):
                    fu = fl.get("file_uuid")
                    if fu and fu not in seen:
                        seen[fu] = (fl.get("file_kind", "image"), fl.get("file_name", ""))

    # Projects: project.files[] (os 17 projects com files)
    proj_dir = raw_dir / "projects"
    if proj_dir.exists():
        for jp in proj_dir.glob("*.json"):
            try:
                with open(jp, encoding="utf-8") as f:
                    proj = json.load(f)
            except Exception:
                continue
            for fl in proj.get("files", []) or []:
                fu = fl.get("file_uuid")
                if fu and fu not in seen:
                    seen[fu] = (fl.get("file_kind", "image"), fl.get("file_name", ""))

    return [(fu, kind, name) for fu, (kind, name) in seen.items()]


async def download_assets(
    client: ClaudeAPIClient,
    raw_dir: Path,
    concurrency: int = 5,
    include_thumbnail: bool = False,
    skip_existing: bool = True,
) -> dict:
    """Download em batch. Retorna dict com estatisticas por kind + errors.

    Regras por file_kind:
    - image: baixa /preview (e /thumbnail se include_thumbnail=True)
    - document: baixa /thumbnail (capa renderizada do PDF)
    - blob: nao baixavel — so registrado
    """
    file_entries = _scan_file_uuids(raw_dir)
    # Agrupa por kind pra relatorio
    by_kind: dict[str, int] = {}
    for _, kind, _ in file_entries:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    print(f"Encontrados {len(file_entries)} files unicos: {by_kind}")

    assets_dir = raw_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    stats = {
        "downloaded": 0,
        "skipped_existing": 0,
        "not_downloadable_blob": 0,
        "errors": [],
    }
    done = 0
    total = len(file_entries)

    async def _one(file_uuid: str, file_kind: str, file_name: str):
        nonlocal done
        variants = list(KIND_VARIANTS.get(file_kind, []))
        if include_thumbnail and file_kind == "image" and "thumbnail" not in variants:
            variants.append("thumbnail")

        if not variants:
            # Blob ou kind desconhecido sem endpoint
            async with sem:
                stats["not_downloadable_blob"] += 1
                done += 1
                return

        async with sem:
            for variant in variants:
                out_path = assets_dir / f"{file_uuid}_{variant}.webp"
                if skip_existing and out_path.exists():
                    stats["skipped_existing"] += 1
                    continue
                try:
                    blob = await client.download_file(file_uuid, variant)
                    out_path.write_bytes(blob)
                    stats["downloaded"] += 1
                except Exception as e:
                    stats["errors"].append((file_uuid, f"{file_kind}/{variant}: {str(e)[:150]}"))
            done += 1
            if done % 50 == 0:
                print(
                    f"  assets [{done}/{total}] dl={stats['downloaded']} "
                    f"skip={stats['skipped_existing']} err={len(stats['errors'])} "
                    f"blob={stats['not_downloadable_blob']}"
                )

    await asyncio.gather(*(_one(fu, kind, name) for fu, kind, name in file_entries))
    print(
        f"  assets [{done}/{total}] dl={stats['downloaded']} "
        f"skip={stats['skipped_existing']} err={len(stats['errors'])} "
        f"blob={stats['not_downloadable_blob']} (final)"
    )
    return stats


def _artifact_ext(art_type: str, language: str | None) -> str:
    """Resolve extensao do arquivo baseado em type + language."""
    if art_type in ARTIFACT_TYPE_EXT and ARTIFACT_TYPE_EXT[art_type]:
        return ARTIFACT_TYPE_EXT[art_type]
    if art_type == "application/vnd.ant.code" and language:
        return LANG_EXT.get(language.lower(), language.lower() or "txt")
    return "txt"


def extract_artifacts(raw_dir: Path, skip_existing: bool = True) -> dict:
    """Extrai artifacts de tool_use blocks como arquivos separados.

    Cada versao (command create/update/rewrite) vira um arquivo. Preserva historico
    via version_uuid. Metadata JSON ao lado com conv_uuid, title, timestamp, cmd.

    Output: assets/artifacts/{conv_uuid}/{artifact_id}_v{N}_{version_uuid[:8]}.{ext}
    """
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists():
        return {"extracted": 0, "skipped_existing": 0, "by_type": {}, "errors": []}

    artifacts_dir = raw_dir / "assets" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    stats = {"extracted": 0, "skipped_existing": 0, "by_type": {}, "errors": []}
    # Conta versoes por (conv, artifact_id) pra nomear v1/v2/...
    version_counter: dict[tuple[str, str], int] = {}

    for jp in sorted(conv_dir.glob("*.json")):
        try:
            with open(jp, encoding="utf-8") as f:
                conv = json.load(f)
        except Exception as e:
            stats["errors"].append((jp.name, f"load: {str(e)[:100]}"))
            continue

        conv_uuid = conv.get("uuid") or jp.stem
        for m in conv.get("chat_messages", []):
            for block in m.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use" or block.get("name") != "artifacts":
                    continue
                inp = block.get("input") or {}
                art_id = inp.get("id") or "unknown"
                cmd = inp.get("command") or "create"
                art_type = inp.get("type") or "text/plain"
                language = inp.get("language")
                title = inp.get("title") or ""
                content = inp.get("content")
                version_uuid = inp.get("version_uuid") or ""

                # Update com str_replace nao tem content — pula
                if cmd == "update" and not content:
                    # str_replace update: guarda metadata mas nao cria novo arquivo
                    continue
                if content is None:
                    continue

                # Incrementa versao pra este (conv, art_id)
                key = (conv_uuid, art_id)
                version_counter[key] = version_counter.get(key, 0) + 1
                v_num = version_counter[key]

                ext = _artifact_ext(art_type, language)
                out_conv_dir = artifacts_dir / conv_uuid
                out_conv_dir.mkdir(parents=True, exist_ok=True)
                vuuid_short = version_uuid[:8] if version_uuid else f"v{v_num}"
                # Sanitiza art_id: ids de Deep Research tipo compass_artifact_wf-*_text/markdown
                # contem '/'; substitui por '_' pra nao quebrar paths
                art_id_safe = art_id.replace("/", "_").replace("\\", "_")
                fname = f"{art_id_safe}_v{v_num}_{vuuid_short}.{ext}"
                out_path = out_conv_dir / fname

                if skip_existing and out_path.exists():
                    stats["skipped_existing"] += 1
                    continue

                try:
                    out_path.write_text(str(content), encoding="utf-8")
                    stats["extracted"] += 1
                    type_key = f"{art_type}|{language or '-'}"
                    stats["by_type"][type_key] = stats["by_type"].get(type_key, 0) + 1

                    # Sidecar metadata
                    meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
                    meta_path.write_text(json.dumps({
                        "conv_uuid": conv_uuid,
                        "artifact_id": art_id,
                        "version": v_num,
                        "version_uuid": version_uuid,
                        "command": cmd,
                        "type": art_type,
                        "language": language,
                        "title": title,
                        "start_timestamp": block.get("start_timestamp"),
                        "stop_timestamp": block.get("stop_timestamp"),
                        "message_uuid": m.get("uuid"),
                        "content_size": len(str(content)),
                    }, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    stats["errors"].append((fname, str(e)[:150]))

    return stats
