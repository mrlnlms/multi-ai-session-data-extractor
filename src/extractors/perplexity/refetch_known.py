"""Refetch state-only de threads ja conhecidas no raw cumulativo.

Caminho confiavel quando o listing /rest/thread/list_ask_threads retorna
parcial (Cloudflare flakey / sessao expirada / discovery upstream
intermitente): pega UUIDs do discovery_ids.json atual (estado da pasta
cumulativa) e refresca cada thread via `client.fetch_thread(uuid)` —
caminho que nao depende de discovery.

Contrato:
- input: `client` ja warmed-up + `raw_dir` com `threads/{uuid}.json` e/ou
  `discovery_ids.json` populados de captures anteriores
- output: dict {total, updated, errors}; cada `threads/{uuid}.json`
  sobrescrito in-place

Raw layout do Perplexity (diferente do ChatGPT):
- Threads sao um arquivo por thread: `threads/{uuid}.json`
- Discovery summary em `discovery_ids.json` (list de {uuid, slug, title, ...})
- Nao existe `_*` aux keys no body da thread — discovery_ids.json carrega
  `is_pinned`, `last_query_datetime`, etc. separadamente
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _collect_known_uuids(raw_dir: Path) -> list[str]:
    """Junta UUIDs do discovery_ids.json + threads/*.json (uniao, ordem estavel).

    Discovery_ids reflete o ultimo listing (estado declarado); threads/ tem o
    que ja foi fetchado historicamente. Uniao captura tanto threads
    descobertas-mas-nao-fetchadas quanto fetchadas-mas-sumidas-do-listing.
    """
    seen: dict[str, None] = {}

    disc_path = raw_dir / "discovery_ids.json"
    if disc_path.exists():
        try:
            disc = json.loads(disc_path.read_text(encoding="utf-8"))
            if isinstance(disc, list):
                for entry in disc:
                    if isinstance(entry, dict):
                        uid = entry.get("uuid")
                        if uid and uid not in seen:
                            seen[uid] = None
        except Exception as exc:
            logger.warning(f"Falha lendo discovery_ids.json: {exc}")

    thread_dir = raw_dir / "threads"
    if thread_dir.exists():
        for p in sorted(thread_dir.glob("*.json")):
            uid = p.stem
            if uid and uid not in seen:
                seen[uid] = None

    return list(seen.keys())


async def refetch_known_perplexity(
    client,
    raw_dir: Path,
    progress: bool = True,
    sleep_between: float = 0.3,
) -> dict:
    """Refetcha todas as threads conhecidas via /rest/thread/{uuid}.

    Reutiliza o `client` ja warmed-up. Sobrescreve cada `threads/{uuid}.json`
    in-place. Retorna {total, updated, errors}.
    """
    thread_dir = raw_dir / "threads"
    thread_dir.mkdir(parents=True, exist_ok=True)

    uuids = _collect_known_uuids(raw_dir)
    total = len(uuids)
    logger.info(f"Refetch-known Perplexity: {total} threads conhecidas")

    updated = 0
    errors = 0
    for i, uid in enumerate(uuids, start=1):
        try:
            data = await client.fetch_thread(uid)
            (thread_dir / f"{uid}.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            updated += 1
        except Exception as exc:
            errors += 1
            logger.warning(f"  refetch {uid[:8]} FAILED: {str(exc)[:120]}")
        if progress and (i % 20 == 0 or i == total):
            logger.info(f"  [{i}/{total}] updated={updated} errors={errors}")
        if sleep_between:
            await asyncio.sleep(sleep_between)

    return {"total": total, "updated": updated, "errors": errors}
