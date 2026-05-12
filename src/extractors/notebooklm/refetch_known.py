"""Refetch state-only de notebooks ja conhecidos no raw cumulativo.

Caminho confiavel quando wXbhsf (list_notebooks) retorna parcial — cenario
analogo ao /conversations listing do ChatGPT. Pega UUIDs dos notebooks ja
salvos em `notebooks/*.json` no raw cumulativo e refresca via os mesmos
RPCs do fetcher original.

Fetch eh COMPOSTO em NotebookLM: cada notebook precisa de metadata + guide
+ chat + notes + audios (+ mind_map + artifacts individuais + sources).
**Reusa `fetch_notebook` do fetcher** — mesma logica, mesmo raw layout,
mesmo skip-existing pra artifacts/sources.

Contrato:
- input: `client` autenticado + `account_dir` com `notebooks/*.json`
- output: dict {total, updated, errors}; raws sobrescritos in-place
- skip-existing de artifact/source/mind_map_tree eh herdado do fetcher
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from src.extractors.notebooklm.api_client import NotebookLMClient
from src.extractors.notebooklm.fetcher import fetch_notebook

logger = logging.getLogger(__name__)


def _load_known_notebooks(account_dir: Path) -> list[tuple[str, str]]:
    """Le `notebooks/*.json` do raw cumulativo, retorna [(uuid, title), ...].

    Pula arquivos auxiliares (`*_mind_map_tree.json`) — so notebook principal.
    """
    nb_dir = account_dir / "notebooks"
    if not nb_dir.exists():
        return []
    items: list[tuple[str, str]] = []
    for f in sorted(nb_dir.glob("*.json")):
        name = f.stem
        # Pular arquivos auxiliares (*_mind_map_tree, *_artifacts/, etc)
        if name.endswith("_mind_map_tree") or "_" in name and not _is_uuid(name):
            continue
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        uuid = raw.get("uuid") or name
        title = raw.get("title") or ""
        items.append((uuid, title))
    return items


def _is_uuid(s: str) -> bool:
    """Heuristica: UUID v4 tem 36 chars com 4 hifens."""
    return len(s) == 36 and s.count("-") == 4


async def refetch_known_notebooklm(
    client: NotebookLMClient,
    account_dir: Path,
    progress: bool = True,
    source_concurrency: int = 2,
) -> dict:
    """Refetch composto de todos os notebooks conhecidos no raw cumulativo.

    Pra cada notebook salvo em `notebooks/*.json`, chama o `fetch_notebook`
    do fetcher (mesma logica usada na captura normal — metadata + guide +
    chat + notes + audios + mind_map + artifacts individuais + sources com
    skip-existing). Mantem o raw layout intacto.

    Retorna {total, updated, errors}.
    """
    known = _load_known_notebooks(account_dir)
    total = len(known)
    if total == 0:
        logger.warning(f"refetch_known_notebooklm: sem notebooks conhecidos em {account_dir}")
        return {"total": 0, "updated": 0, "errors": 0}

    logger.info(f"Refetch-known NotebookLM: {total} notebooks (composite fetch)")

    updated = 0
    errors = 0
    for i, (uuid, title) in enumerate(known):
        try:
            stats = await fetch_notebook(
                client, uuid, title, account_dir,
                source_concurrency=source_concurrency,
            )
            if stats.get("rpcs_errors"):
                errors += 1
            else:
                updated += 1
            if progress:
                marker = "ok" if not stats.get("rpcs_errors") else f"err={len(stats['rpcs_errors'])}"
                logger.info(
                    f"  [{i+1}/{total}] {uuid[:8]} {title[:40]!r} — {marker}, "
                    f"sources={stats.get('sources_fetched', 0)}/{stats.get('n_source_uuids', 0)}"
                )
        except Exception as e:
            errors += 1
            logger.warning(f"  [{i+1}/{total}] {uuid[:8]} FAILED: {str(e)[:120]}")
        await asyncio.sleep(0.1)

    return {"total": total, "updated": updated, "errors": errors}
