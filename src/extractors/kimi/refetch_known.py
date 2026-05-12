"""Refetch state-only de chats Kimi ja conhecidos no raw cumulativo.

Caminho confiavel quando ListChats retorna paginacao parcial: pega chatIds dos
arquivos `conversations/{id}.json` ja salvos e refresca cada um via
`client.fetch_full_chat(chat_id)` (GetChat + ListMessages) — chamada por ID que
nao depende de discovery.

Contrato:
- input: `client` ja warmed up + `raw_dir` apontando pra pasta cumulativa
- output: dict {total, updated, errors}; cada `conversations/{id}.json`
  sobrescrito in-place preservando chaves auxiliares `_*` (ex:
  `_last_seen_in_server`)
- fallback usa `conversations/*.json` como source of truth (consistente com
  qwen/deepseek/claude_ai)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


async def refetch_known_kimi(
    client,
    raw_dir: Path,
    progress: bool = True,
) -> dict:
    """Atualiza state de todos os chats conhecidos via fetch_full_chat por ID.

    Le IDs do diretorio `raw_dir/conversations/`. Pra cada chat_id chama
    `client.fetch_full_chat(chat_id)` e sobrescreve o arquivo local preservando
    aux keys (`_*`) e tagueando `_last_seen_in_server` com hoje.

    Retorna {total, updated, errors}.
    """
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists() or not conv_dir.is_dir():
        raise FileNotFoundError(f"conversations dir nao existe: {conv_dir}")

    chat_ids = sorted(p.stem for p in conv_dir.glob("*.json"))
    total = len(chat_ids)
    logger.info(f"Refetch-known Kimi: {total} chats em conversations/")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated = 0
    errors = 0

    for i, cid in enumerate(chat_ids, start=1):
        out = conv_dir / f"{cid}.json"
        try:
            existing: dict = {}
            try:
                existing = json.loads(out.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            try:
                new = await client.fetch_full_chat(cid)
            except Exception as exc:
                errors += 1
                if progress:
                    logger.warning(f"  [{i}/{total}] {cid[:8]} FAILED: {str(exc)[:120]}")
                await asyncio.sleep(0.3)
                continue
            if not isinstance(new, dict):
                errors += 1
                continue
            # Preserva chaves auxiliares `_*` do envelope existente
            aux = {k: v for k, v in existing.items() if isinstance(k, str) and k.startswith("_")}
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
