"""Refetch state-only de convs Qwen ja conhecidas no raw cumulativo.

Caminho confiavel quando /api/v2/chats listing retorna parcial: pega IDs dos
arquivos `conversations/{id}.json` ja salvos no raw cumulativo e refresca cada
um via `client.fetch_conversation(conv_id)` (passa por auth nativa do client).

Contrato:
- input: `client` ja warmed up + `raw_dir` apontando pra pasta cumulativa
- output: dict {total, updated, errors}; cada `conversations/{id}.json`
  sobrescrito in-place preservando chaves auxiliares `_*` (ex: `_last_seen_in_server`)
- nao depende de discovery — usa os IDs ja presentes no disco como source of truth
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.qwen.api_client import QwenAPIClient

logger = logging.getLogger(__name__)


async def refetch_known_qwen(
    client: QwenAPIClient,
    raw_dir: Path,
    progress: bool = True,
) -> dict:
    """Atualiza state de todas as convs conhecidas via /api/v2/chats/{id}.

    Le IDs do diretorio `raw_dir/conversations/`. Pra cada conv_id chama
    `client.fetch_conversation(conv_id)` e sobrescreve o arquivo local
    preservando aux keys (`_*`) e tagueando `_last_seen_in_server` com hoje.

    Retorna {total, updated, errors}.
    """
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists():
        logger.warning(f"conversations dir nao existe: {conv_dir}")
        return {"total": 0, "updated": 0, "errors": 0}

    conv_ids = sorted(p.stem for p in conv_dir.glob("*.json"))
    total = len(conv_ids)
    logger.info(f"Refetch-known Qwen: {total} convs em conversations/")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated = 0
    errors = 0

    for i, cid in enumerate(conv_ids, start=1):
        out = conv_dir / f"{cid}.json"
        try:
            existing: dict = {}
            try:
                existing = json.loads(out.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            new = await client.fetch_conversation(cid)
            if not new.get("success", False):
                errors += 1
                if progress:
                    logger.warning(f"  [{i}/{total}] {cid[:8]} api success=false")
                continue
            # Preserva chaves auxiliares `_*` do envelope existente
            aux = {k: v for k, v in existing.items() if k.startswith("_")}
            new.update(aux)
            new["_last_seen_in_server"] = today
            out.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
            updated += 1
        except Exception as exc:
            errors += 1
            if progress:
                logger.warning(f"  [{i}/{total}] {cid[:8]} FAILED: {str(exc)[:120]}")
            await asyncio.sleep(0.3)
            continue
        if progress and i % 20 == 0:
            logger.info(f"  [{i}/{total}] updated={updated} errors={errors}")

    logger.info(f"Refetch-known done: total={total} updated={updated} errors={errors}")
    return {"total": total, "updated": updated, "errors": errors}
