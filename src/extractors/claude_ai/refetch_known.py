"""Refetch state-only de convs ja conhecidas no raw cumulativo de Claude.ai.

Caminho confiavel quando o listing /chat_conversations_v2 retorna parcial
(sessao parcial / endpoint flakey / cenario equivalente ao da ChatGPT):
pega IDs do raw cumulativo (`conversations/*.json` ou
`discovery_ids.json`) e re-fetcha cada um via `client.fetch_conversation`.

Contrato:
- input: `client` autenticado + `raw_dir` com `conversations/` ou `discovery_ids.json`
- output: dict {total, updated, errors}; cada `<uuid>.json` sobrescrito in-place
- preserva chaves auxiliares `_*` (ex: `_last_seen_in_server`, `_preserved_missing`)
  do arquivo existente
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0


def _collect_known_ids(raw_dir: Path) -> list[str]:
    """Junta IDs do raw cumulativo: prefere conversations/*.json, fallback discovery_ids.json.

    Ordem reflete realidade do raw cumulativo: convs/ tem o que ja foi capturado;
    discovery_ids cobre o caso de raw cru sem nenhum fetch feito ainda.
    """
    conv_dir = raw_dir / "conversations"
    ids: list[str] = []
    seen: set[str] = set()
    if conv_dir.exists():
        for p in conv_dir.glob("*.json"):
            uid = p.stem
            if uid and uid not in seen:
                seen.add(uid)
                ids.append(uid)
    if ids:
        return ids
    disc = raw_dir / "discovery_ids.json"
    if disc.exists():
        try:
            data = json.loads(disc.read_text(encoding="utf-8"))
            for c in data.get("conversations", []):
                uid = c.get("uuid")
                if uid and uid not in seen:
                    seen.add(uid)
                    ids.append(uid)
        except Exception as exc:
            logger.warning(f"Falha lendo discovery_ids.json: {exc}")
    return ids


async def _fetch_with_retry(
    client,
    uuid: str,
    retries: int,
    backoff_base: float,
) -> tuple[dict | None, str | None]:
    """Tenta fetchar conv com exp backoff. Retorna (conv, err_msg)."""
    last_err = ""
    for attempt in range(retries + 1):
        try:
            conv = await client.fetch_conversation(uuid)
            return conv, None
        except Exception as e:
            last_err = str(e)[:200]
            if attempt < retries:
                wait = backoff_base * (2**attempt)
                await asyncio.sleep(wait)
    return None, last_err


async def refetch_known_claude_ai(
    client,
    raw_dir: Path,
    retries: int = DEFAULT_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
) -> dict:
    """Atualiza state de todas as convs conhecidas via `client.fetch_conversation`.

    Sobrescreve `<raw_dir>/conversations/<uuid>.json` in-place; preserva chaves
    auxiliares `_*` (ex: `_last_seen_in_server`, `_preserved_missing`).

    Retorna {total, updated, errors}.
    """
    conv_ids = _collect_known_ids(raw_dir)
    total = len(conv_ids)
    logger.info(f"Refetch-known Claude.ai: {total} convs")

    conv_dir = raw_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    updated = 0
    errors = 0
    for i, uuid in enumerate(conv_ids, start=1):
        existing_path = conv_dir / f"{uuid}.json"
        aux: dict = {}
        if existing_path.exists():
            try:
                existing = json.loads(existing_path.read_text(encoding="utf-8"))
                aux = {k: v for k, v in existing.items() if k.startswith("_")}
            except Exception:
                aux = {}

        conv, err = await _fetch_with_retry(client, uuid, retries, backoff_base)
        if conv is None:
            errors += 1
            logger.warning(f"  [{i}/{total}] {uuid} FALHOU: {(err or '')[:120]}")
        else:
            # Preserva auxiliares anteriores
            conv.update(aux)
            existing_path.write_text(
                json.dumps(conv, ensure_ascii=False), encoding="utf-8"
            )
            updated += 1
        logger.info(f"  [{i}/{total}] updated={updated} errors={errors}")

    return {"total": total, "updated": updated, "errors": errors}
