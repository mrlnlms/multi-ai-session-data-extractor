"""Refetch state-only de convs ja conhecidas no raw cumulativo (Gemini).

Caminho confiavel quando MaZiqc retorna parcial (rpcid hash mudando, response
400, etc): le os UUIDs do `discovery_ids.json` atual da conta e refresca cada
conv via hNvQHb (`client.fetch_conversation(uuid)`) — caminho que NAO depende
de discovery.

Contrato:
- input: `client` autenticado + `account_dir` (ex: data/raw/Gemini/account-1)
- output: dict {total, updated, errors}; arquivos `conversations/<uuid>.json`
  sobrescritos in-place
- preserva chaves auxiliares `_*` (ex: `_last_seen_in_server`) por conv
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.gemini.api_client import GeminiAPIClient

logger = logging.getLogger(__name__)


async def refetch_known_gemini(
    client: GeminiAPIClient,
    account_dir: Path,
    progress: bool = True,
) -> dict:
    """Atualiza estado de todas as convs conhecidas via hNvQHb (fetch_conversation).

    Le UUIDs de `account_dir/discovery_ids.json`. Pra cada uuid chama
    `client.fetch_conversation(uuid)` e sobrescreve `conversations/<uuid>.json`,
    preservando chaves auxiliares `_*` (`_last_seen_in_server` etc).

    Retorna {total, updated, errors}.
    """
    disc_path = account_dir / "discovery_ids.json"
    if not disc_path.exists():
        raise FileNotFoundError(f"discovery_ids.json nao existe: {disc_path}")

    try:
        disc = json.loads(disc_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"discovery_ids.json corrompido em {disc_path}: {exc}")

    conv_uuids = [c["uuid"] for c in disc if isinstance(c, dict) and c.get("uuid")]
    total = len(conv_uuids)
    logger.info(f"Refetch-known Gemini: {total} convs em {account_dir}")

    conv_dir = account_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    updated = 0
    errors = 0
    for i, uuid in enumerate(conv_uuids, start=1):
        out = conv_dir / f"{uuid}.json"
        # Preserva chaves auxiliares do arquivo existente (se houver)
        aux: dict = {}
        if out.exists():
            try:
                existing = json.loads(out.read_text(encoding="utf-8"))
                aux = {k: v for k, v in existing.items() if k.startswith("_")}
            except Exception:
                aux = {}

        try:
            conv = await client.fetch_conversation(uuid)
        except Exception as exc:
            logger.warning(f"  [{i}/{total}] {uuid[:18]}... FAILED: {str(exc)[:120]}")
            errors += 1
            await asyncio.sleep(0.5)
            continue

        if conv is None:
            logger.warning(f"  [{i}/{total}] {uuid[:18]}... returned None")
            errors += 1
            continue

        # Merge: nao deixa fetch_conversation pisar em chaves auxiliares
        conv.update(aux)
        conv["_last_seen_in_server"] = today

        try:
            out.write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
            updated += 1
        except Exception as exc:
            logger.warning(f"  [{i}/{total}] {uuid[:18]}... write FAILED: {exc}")
            errors += 1
            continue

        if progress and (i % 20 == 0 or i == total):
            logger.info(f"  [{i}/{total}] updated={updated} errors={errors}")
        await asyncio.sleep(0.3)

    return {"total": total, "updated": updated, "errors": errors}
