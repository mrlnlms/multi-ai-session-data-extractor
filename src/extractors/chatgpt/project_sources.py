"""Download dos knowledge files (sources) de todos os projects do ChatGPT.

Endpoint mapeado empiricamente em 24/abr/2026:
    GET /backend-api/gizmos/{project_id}         # retorna { files: [...] }
    GET /backend-api/files/download/{file_id}?gizmo_id={project_id}
                                                  # retorna download_url presigned

Saida em data/raw/ChatGPT Data <date>/project_sources/{project_id}/{file_name}
+ um indice JSON por project com metadata dos files.

Preservation: files removidas do servidor sao preservadas no indice com
`_preserved_missing: true` e `_last_seen_in_server`. Mesmo padrao do
reconciler de conversations — historia local nunca e perdida.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from src.extractors.chatgpt.api_client import ChatGPTAPIClient


def _safe_filename(name: str) -> str:
    """Sanitiza nomes pra filesystem (remove /, \\, etc)."""
    for ch in ("/", "\\", ":", "\x00"):
        name = name.replace(ch, "_")
    return name[:200]  # truncate


def _merge_with_preserved(current_files: list[dict], existing_index_path: Path) -> tuple[list[dict], int]:
    """Merge files atuais com files preservadas de runs anteriores.

    Files presentes em runs anteriores mas ausentes na atual viram
    _preserved_missing=True (mesma filosofia do reconciler de conversations).

    Returns: (merged_list, count_preserved)
    """
    if not existing_index_path.exists():
        return list(current_files), 0
    try:
        with open(existing_index_path, encoding="utf-8") as fh:
            old_files = json.load(fh)
    except Exception:
        return list(current_files), 0
    if not isinstance(old_files, list):
        return list(current_files), 0

    today = datetime.now().strftime("%Y-%m-%d")
    current_ids = {f.get("file_id") for f in current_files if f.get("file_id")}
    preserved = []
    for old_f in old_files:
        fid = old_f.get("file_id")
        if not fid or fid in current_ids:
            continue
        # Ja era preserved? mantem _last_seen_in_server original
        if not old_f.get("_preserved_missing"):
            old_f["_preserved_missing"] = True
            old_f.setdefault("_last_seen_in_server", today)
        preserved.append(old_f)
    return list(current_files) + preserved, len(preserved)


async def download_project_sources(
    client: ChatGPTAPIClient,
    project_ids: list[str],
    output_dir: Path,
    concurrency: int = 3,
    skip_existing: bool = True,
) -> dict:
    """Pra cada project_id, pega lista de files e baixa binarios.

    Salva em {output_dir}/project_sources/{project_id}/{safe_name}.
    Indice em {output_dir}/project_sources/{project_id}/_files.json.

    Retorna stats dict: projects_with_files, total_files, downloaded, skipped, errors.
    """
    root = output_dir / "project_sources"
    root.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    stats = {
        "projects_scanned": 0,
        "projects_with_files": 0,
        "total_files": 0,
        "downloaded": 0,
        "skipped_existing": 0,
        "preserved_missing": 0,
        "errors": [],
    }

    async def _process_project(pid: str):
        async with sem:
            try:
                files = await client.fetch_project_files(pid)
            except Exception as e:
                stats["errors"].append((pid, f"list: {str(e)[:150]}"))
                stats["projects_scanned"] += 1
                return

        stats["projects_scanned"] += 1
        if not files:
            return
        stats["projects_with_files"] += 1
        stats["total_files"] += len(files)

        pdir = root / pid
        pdir.mkdir(parents=True, exist_ok=True)
        # Merge com preserved (files removidas do servidor mas presentes em runs anteriores)
        index_path = pdir / "_files.json"
        merged_files, preserved_count = _merge_with_preserved(files, index_path)
        stats["preserved_missing"] += preserved_count
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(merged_files, f, ensure_ascii=False, indent=2)

        for f in files:
            fid = f.get("file_id")
            name = f.get("name") or fid
            safe_name = _safe_filename(name)
            out_path = pdir / safe_name
            if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
                stats["skipped_existing"] += 1
                continue
            try:
                url = await client.get_project_file_download_url(fid, pid)
                if not url:
                    stats["errors"].append((fid, f"{pid}: permission_error"))
                    continue
                blob = await client.download_binary(url)
                if blob is None:
                    stats["errors"].append((fid, f"{pid}: download failed"))
                    continue
                out_path.write_bytes(blob)
                stats["downloaded"] += 1
            except Exception as e:
                stats["errors"].append((fid, f"{pid}: {str(e)[:150]}"))

    print(f"Scaneando {len(project_ids)} projects pra files...")
    await asyncio.gather(*(_process_project(pid) for pid in project_ids))

    print(
        f"Scanned {stats['projects_scanned']} projects, "
        f"{stats['projects_with_files']} com files, "
        f"{stats['total_files']} files total"
    )
    print(
        f"Downloaded: {stats['downloaded']}, "
        f"skipped: {stats['skipped_existing']}, "
        f"preserved_missing: {stats['preserved_missing']}, "
        f"errors: {len(stats['errors'])}"
    )
    return stats
