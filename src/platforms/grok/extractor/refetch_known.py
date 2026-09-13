"""Refetch full de convs Grok ja conhecidas no raw cumulativo.

Caminho confiavel quando o listing /rest/app-chat/conversations retorna parcial
(cenario upstream comum): pega IDs do `discovery_ids.json` atual (ou dos arquivos
em `conversations/`) e refetcha cada conv via `client.fetch_full_conversation`
(meta + response_node + responses + files + share_links).

Contrato:
- input: `client` ja inicializado + `raw_dir` com `discovery_ids.json` ou
  `conversations/*.json` previo
- output: dict {total, updated, errors}; cada `conversations/{cid}.json`
  sobrescrito in-place; preserva chaves auxiliares `_*` do arquivo existente
  (ex: `_last_seen_in_server`)

Reutiliza `client.fetch_full_conversation` (a mesma funcao que o fetcher usa)
pra nao duplicar logica de full fetch composto.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_known_conv_ids(raw_dir: Path) -> list[str]:
    """Le IDs do raw cumulativo. Preferencia: discovery_ids.json -> dir listing."""
    disc = raw_dir / "discovery_ids.json"
    if disc.exists():
        try:
            data = json.loads(disc.read_text(encoding="utf-8"))
            ids = [c.get("conversationId") for c in data if c.get("conversationId")]
            if ids:
                return ids
        except Exception as exc:
            logger.warning(f"discovery_ids.json ilegivel ({exc}); fallback pra conversations/")
    conv_dir = raw_dir / "conversations"
    if not conv_dir.exists():
        return []
    return sorted(p.stem for p in conv_dir.glob("*.json"))


async def refetch_known_grok(
    client,
    raw_dir: Path,
    progress: bool = True,
) -> dict:
    """Refetcha full de cada conv conhecida usando fetch_full_conversation.

    Sobrescreve cada `raw_dir/conversations/{cid}.json` in-place; preserva
    chaves `_*` do arquivo existente (ex: `_last_seen_in_server`).

    Retorna {total, updated, errors}.
    """
    conv_ids = _load_known_conv_ids(raw_dir)
    total = len(conv_ids)
    if total == 0:
        raise FileNotFoundError(
            f"Nenhum conv_id conhecido em {raw_dir} (sem discovery_ids.json nem conversations/)"
        )
    logger.info(f"Refetch-known Grok: {total} convs")

    conv_dir = raw_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    updated = 0
    errors = 0
    for i, cid in enumerate(conv_ids, start=1):
        out = conv_dir / f"{cid}.json"
        # Preserva chaves auxiliares do arquivo existente
        aux: dict = {}
        if out.exists():
            try:
                existing = json.loads(out.read_text(encoding="utf-8"))
                aux = {k: v for k, v in existing.items() if k.startswith("_")}
            except Exception:
                pass
        try:
            data = await client.fetch_full_conversation(cid)
        except Exception as exc:
            errors += 1
            logger.warning(f"  [{i}/{total}] cid={cid} FAILED: {str(exc)[:120]}")
            if progress and i % 20 == 0:
                logger.info(f"  [{i}/{total}] updated={updated} errors={errors}")
            await asyncio.sleep(0.2)
            continue
        data.update(aux)
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        updated += 1
        if progress and i % 20 == 0:
            logger.info(f"  [{i}/{total}] updated={updated} errors={errors}")
        await asyncio.sleep(0.2)

    logger.info(f"  [{total}/{total}] updated={updated} errors={errors} (final)")
    return {"total": total, "updated": updated, "errors": errors}
