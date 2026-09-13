"""Refetch state-only de convs ja conhecidas no raw cumulativo (DeepSeek).

Caminho confiavel quando o listing `chat_session/fetch_page` retorna parcial:
pega IDs do raw cumulativo (`conversations/*.json`) e refresca cada um via
`client.fetch_conversation(conv_id)` — chamada por ID que nao depende de
discovery.

Contrato:
- input: `client` ja com warmup feito + `raw_dir` com `conversations/*.json`
- output: dict {total, updated, errors}; arquivos `conversations/{id}.json`
  sobrescritos in-place
- preserva chaves auxiliares `_*` (ex: `_last_seen_in_server`)
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def refetch_known_deepseek(
    client,
    raw_dir: Path,
    progress: bool = True,
) -> dict:
    """Atualiza state de todas as convs conhecidas via fetch_conversation por ID.

    Le `raw_dir/conversations/*.json`, refetcha cada uma via
    `client.fetch_conversation(conv_id)` e sobrescreve in-place. Preserva chaves
    auxiliares (prefixo `_`) do arquivo existente.

    Retorna {total, updated, errors}.
    """
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists() or not conv_dir.is_dir():
        raise FileNotFoundError(f"conversations dir nao existe: {conv_dir}")

    conv_files = sorted(conv_dir.glob("*.json"))
    total = len(conv_files)
    logger.info(f"Refetch-known DeepSeek: {total} convs")

    updated = 0
    errors = 0
    for i, path in enumerate(conv_files, start=1):
        conv_id = path.stem
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"  [{i}/{total}] falha lendo existing {conv_id}: {exc}")
            existing = {}
        aux = {k: v for k, v in existing.items() if isinstance(k, str) and k.startswith("_")}
        try:
            new = await client.fetch_conversation(conv_id)
        except Exception as exc:
            logger.warning(f"  [{i}/{total}] fetch FAILED {conv_id}: {str(exc)[:120]}")
            errors += 1
            await asyncio.sleep(0.5)
            continue
        if not isinstance(new, dict):
            errors += 1
            continue
        new.update(aux)
        path.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
        updated += 1
        if progress and i % 20 == 0:
            logger.info(f"  [{i}/{total}] updated={updated} errors={errors}")
        await asyncio.sleep(0.2)

    logger.info(f"  [{total}/{total}] updated={updated} errors={errors} (final)")
    return {"total": total, "updated": updated, "errors": errors}
