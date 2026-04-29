"""Captura Spaces (collections na API). Cada space pode ter:
metadata, threads, files. Saida em spaces/{uuid}/{metadata,threads_index,files}.json.

Threads dentro de spaces sao as MESMAS de list_ask_threads (validado empiricamente
em 2026-04-29) — list_collection_threads e view filtrada. Nao precisa re-fetchar
thread bodies. Mas o mapping thread->space e preservado em threads_index.json.
"""

import json
from pathlib import Path

from src.extractors.perplexity.api_client import PerplexityAPIClient


async def discover_spaces(client: PerplexityAPIClient, output_dir: Path) -> list[dict]:
    """Lista todas as collections do user, salva _index.json enxuto."""
    print("Descobrindo spaces...")
    collections = await client.list_user_collections()
    print(f"  {len(collections)} spaces")

    spaces_dir = output_dir / "spaces"
    spaces_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "uuid": c.get("uuid"),
            "title": c.get("title") or "",
            "slug": c.get("slug"),
            "emoji": c.get("emoji"),
            "access": c.get("access"),
            "user_permission": c.get("user_permission"),
            "thread_count": c.get("thread_count"),
            "page_count": c.get("page_count"),
            "file_count": c.get("file_count"),
            "updated_datetime": c.get("updated_datetime"),
        }
        for c in collections if c.get("uuid")
    ]
    with open(spaces_dir / "_index.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return collections


async def fetch_spaces(
    client: PerplexityAPIClient,
    collections: list[dict],
    output_dir: Path,
) -> tuple[int, int, list[tuple[str, str]]]:
    """Pra cada space: salva metadata + threads_index + files. Retorna (ok, skip, errors)."""
    spaces_dir = output_dir / "spaces"
    spaces_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    skip = 0
    errors: list[tuple[str, str]] = []

    for i, c in enumerate(collections, start=1):
        uuid = c.get("uuid")
        slug = c.get("slug")
        title = c.get("title") or "?"
        if not uuid or not slug:
            errors.append((str(uuid), "missing uuid or slug"))
            continue

        space_dir = spaces_dir / uuid
        space_dir.mkdir(parents=True, exist_ok=True)

        try:
            metadata = await client.get_collection(slug)
            with open(space_dir / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            threads_in_space = await client.list_all_collection_threads(slug)
            threads_summary = [
                {
                    "uuid": t.get("uuid"),
                    "slug": t.get("slug"),
                    "title": t.get("title") or "",
                    "last_query_datetime": t.get("last_query_datetime"),
                    "mode": t.get("mode"),
                }
                for t in threads_in_space if t.get("uuid")
            ]
            with open(space_dir / "threads_index.json", "w", encoding="utf-8") as f:
                json.dump(threads_summary, f, ensure_ascii=False, indent=2)

            files = await client.list_collection_files(uuid)
            with open(space_dir / "files.json", "w", encoding="utf-8") as f:
                json.dump(files, f, ensure_ascii=False, indent=2)

            ok += 1
            print(f"  [{i}/{len(collections)}] {title!r}: {len(threads_summary)} threads, {len(files)} files")
        except Exception as e:
            errors.append((uuid, str(e)[:200]))
            print(f"  [{i}/{len(collections)}] {title!r}: ERRO {str(e)[:120]}")

    return ok, skip, errors
