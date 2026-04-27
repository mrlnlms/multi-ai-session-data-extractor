"""Fetcher: pega todos os RPCs per notebook + source content.

Salva raw responses em:
  notebooks/{uuid}.json    — dict com metadata, guide, chat, notes, audios, mind_map, list_data
  sources/{source_uuid}.json  — hizoJc response com texto extraido + image URLs

Parse em schema normalizado fica pro parser (futuro).
"""

import asyncio
import json
from pathlib import Path

from src.extractors.notebooklm.api_client import NotebookLMClient


def _extract_source_uuids(metadata_raw) -> list[str]:
    """Do rLM1Ne response extrai lista de source UUIDs.

    Schema: data[0] = [title, [sources...], uuid, emoji, ...]
    Cada source em [1]: [[uuid], filename, [meta], [flag]]
    """
    if not isinstance(metadata_raw, list) or not metadata_raw:
        return []
    outer = metadata_raw[0] if isinstance(metadata_raw[0], list) else None
    if not outer or len(outer) < 2 or not isinstance(outer[1], list):
        return []
    uuids = []
    for s in outer[1]:
        if isinstance(s, list) and s and isinstance(s[0], list) and s[0]:
            uid = s[0][0]
            if isinstance(uid, str):
                uuids.append(uid)
    return uuids


async def lite_fetch_notebook(
    client: NotebookLMClient,
    nb_uuid: str,
) -> dict:
    """Fetch leve: so 3 RPCs (rLM1Ne + cFji9 + gArtLc) pra detectar mudancas.

    Retorna {metadata, notes, audios} sem fetch de sources, chat, guide, mind_map.
    Usado pra comparar com raw anterior antes de decidir full fetch.
    """
    results = await asyncio.gather(
        client.fetch_metadata(nb_uuid),
        client.fetch_notes(nb_uuid),
        client.fetch_artifacts(nb_uuid),
        return_exceptions=True,
    )
    return {
        "metadata": results[0] if not isinstance(results[0], Exception) else None,
        "notes": results[1] if not isinstance(results[1], Exception) else None,
        "audios": results[2] if not isinstance(results[2], Exception) else None,
    }


async def fetch_notebook(
    client: NotebookLMClient,
    nb_uuid: str,
    nb_title: str,
    output_dir: Path,
    source_concurrency: int = 2,
) -> dict:
    """Fetcha todos os RPCs do notebook + sources. Retorna stats."""
    nb_dir = output_dir / "notebooks"
    nb_dir.mkdir(parents=True, exist_ok=True)
    sources_dir = output_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "uuid": nb_uuid,
        "title": nb_title,
        "rpcs_ok": 0,
        "rpcs_empty": 0,
        "rpcs_errors": [],
        "sources_fetched": 0,
        "sources_errors": [],
    }

    # Colleta RPCs em paralelo (mesma session, reqids distintos)
    async def _try(name, coro):
        try:
            data = await coro
            if data is None:
                stats["rpcs_empty"] += 1
                return name, None
            stats["rpcs_ok"] += 1
            return name, data
        except Exception as e:
            stats["rpcs_errors"].append((name, str(e)[:200]))
            return name, None

    results = await asyncio.gather(
        _try("metadata", client.fetch_metadata(nb_uuid)),
        _try("guide", client.fetch_guide(nb_uuid)),
        _try("chat", client.fetch_chat(nb_uuid)),
        _try("notes", client.fetch_notes(nb_uuid)),
        _try("audios", client.fetch_audios(nb_uuid)),
        _try("mind_map", client.fetch_mind_map(nb_uuid)),
    )
    nb_data = {name: data for name, data in results}
    nb_data["uuid"] = nb_uuid
    nb_data["title"] = nb_title

    # Salva notebook raw
    with open(nb_dir / f"{nb_uuid}.json", "w", encoding="utf-8") as f:
        json.dump(nb_data, f, ensure_ascii=False)

    # Extrai source UUIDs do metadata
    source_uuids = _extract_source_uuids(nb_data.get("metadata"))

    # Fetcha cada source content com concurrency controlada
    sem = asyncio.Semaphore(source_concurrency)

    async def _fetch_source(suid: str):
        async with sem:
            out = sources_dir / f"{suid}.json"
            if out.exists():
                return  # skip-existing
            try:
                sc = await client.fetch_source_content(nb_uuid, suid)
                if sc is not None:
                    payload = {"source_uuid": suid, "notebook_uuid": nb_uuid, "raw": sc}
                    with open(out, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False)
                    stats["sources_fetched"] += 1
            except Exception as e:
                stats["sources_errors"].append((suid, str(e)[:200]))

    await asyncio.gather(*(_fetch_source(s) for s in source_uuids))
    stats["n_source_uuids"] = len(source_uuids)
    return stats
