"""Fetcher: pega arvore completa por conv e metadata+docs+files por project.

Cada conv vira 1 arquivo JSON em conversations/{uuid}.json.
Cada project vira 1 arquivo em projects/{uuid}.json com docs e files inline.
"""

import asyncio
import json
from pathlib import Path

from src.extractors.claude_ai.api_client import ClaudeAPIClient


async def fetch_conversations(
    client: ClaudeAPIClient,
    conv_uuids: list[str],
    output_dir: Path,
    concurrency: int = 3,
    skip_existing: bool = True,
) -> tuple[int, int, list[tuple[str, str]]]:
    """Fetcha N convs com arvore completa. Retorna (ok, skip, errors).

    errors: lista de (uuid, msg). Nao falha o batch inteiro por 1 erro.
    """
    conv_dir = output_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    ok = 0
    skip = 0
    errors: list[tuple[str, str]] = []
    total = len(conv_uuids)
    done = 0

    async def _one(uuid: str):
        nonlocal ok, skip, done
        out = conv_dir / f"{uuid}.json"
        if skip_existing and out.exists():
            async with sem:
                skip += 1
                done += 1
                if done % 50 == 0:
                    print(f"  [{done}/{total}] ok={ok} skip={skip} err={len(errors)}")
                return
        async with sem:
            try:
                conv = await client.fetch_conversation(uuid)
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(conv, f, ensure_ascii=False)
                ok += 1
            except Exception as e:
                errors.append((uuid, str(e)[:200]))
            done += 1
            if done % 50 == 0:
                print(f"  [{done}/{total}] ok={ok} skip={skip} err={len(errors)}")

    await asyncio.gather(*(_one(u) for u in conv_uuids))
    print(f"  [{done}/{total}] ok={ok} skip={skip} err={len(errors)} (final)")
    return ok, skip, errors


async def fetch_projects(
    client: ClaudeAPIClient,
    project_uuids: list[str],
    output_dir: Path,
    concurrency: int = 3,
    skip_existing: bool = True,
) -> tuple[int, int, list[tuple[str, str]]]:
    """Fetcha N projects com docs e files inline. Retorna (ok, skip, errors)."""
    proj_dir = output_dir / "projects"
    proj_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    ok = 0
    skip = 0
    errors: list[tuple[str, str]] = []
    total = len(project_uuids)
    done = 0

    async def _one(uuid: str):
        nonlocal ok, skip, done
        out = proj_dir / f"{uuid}.json"
        if skip_existing and out.exists():
            async with sem:
                skip += 1
                done += 1
                return
        async with sem:
            try:
                metadata = await client.fetch_project(uuid)
                docs = await client.list_project_docs(uuid)
                files = await client.list_project_files(uuid)
                payload = {**metadata, "docs": docs, "files": files}
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                ok += 1
            except Exception as e:
                errors.append((uuid, str(e)[:200]))
            done += 1
            if done % 20 == 0:
                print(f"  projects [{done}/{total}] ok={ok} skip={skip} err={len(errors)}")

    await asyncio.gather(*(_one(u) for u in project_uuids))
    print(f"  projects [{done}/{total}] ok={ok} skip={skip} err={len(errors)} (final)")
    return ok, skip, errors
