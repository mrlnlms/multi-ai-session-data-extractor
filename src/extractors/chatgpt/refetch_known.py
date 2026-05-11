"""Refetch state-only de convs ja conhecidas no raw cumulativo.

Caminho confiavel quando /conversations listing retorna parcial (cenario
upstream comum): pega IDs do `chatgpt_raw.json` atual e refresca state via
`/conversations/batch` (page.evaluate, passa por Cloudflare/auth nativo).

Contrato:
- input: `page` ja navegada em chatgpt.com + `raw_dir` com `chatgpt_raw.json`
- output: dict {total, updated, errors}; raw_path sobrescrito in-place
- limite upstream: batch <= 10 (validado 2026-05-11; antes era 50)
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 10  # limite upstream do /conversations/batch (2026-05-11)


async def fetch_batch(page, ids: list[str]) -> tuple[list[dict], str | None]:
    """Fetch batch via page.evaluate (fetch nativo). Retorna (results, error_msg)."""
    payload = json.dumps({"ids": ids})
    result = await page.evaluate(
        """async ({payload}) => {
            const sess = await fetch('/api/auth/session', {credentials: 'include'});
            const tok = (await sess.json()).accessToken;
            const ids = JSON.parse(payload).ids;
            const r = await fetch('/backend-api/conversations/batch', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Authorization': 'Bearer ' + tok,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({conversation_ids: ids}),
            });
            const txt = await r.text();
            return {status: r.status, body: txt};
        }""",
        {"payload": payload},
    )
    if result["status"] == 200:
        return json.loads(result["body"]), None
    return [], f"HTTP {result['status']}: {result['body'][:200]}"


async def refetch_known_via_page(
    page,
    raw_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: bool = True,
) -> dict:
    """Atualiza state de todas as convs conhecidas via /conversations/batch.

    Reutiliza a page passada (deve estar navegada em chatgpt.com com auth).
    Sobrescreve `raw_dir/chatgpt_raw.json` in-place; preserva chaves auxiliares
    `_*` (ex: `_preserved_missing`, `_last_seen_in_server`).

    Retorna {total, updated, errors}.
    """
    raw_path = raw_dir / "chatgpt_raw.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"raw nao existe: {raw_path}")

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    conv_ids = list(raw["conversations"].keys())
    total = len(conv_ids)
    logger.info(f"Refetch-known: {total} convs em batches de {batch_size}")

    updated = 0
    errors = 0
    for i in range(0, total, batch_size):
        batch = conv_ids[i : i + batch_size]
        results, err = await fetch_batch(page, batch)
        if err:
            logger.warning(f"  batch [{i}..{i+len(batch)}] FAILED: {err[:120]}")
            errors += len(batch)
            await asyncio.sleep(2)
            continue
        by_id = {r.get("id"): r for r in results if isinstance(r, dict) and r.get("id")}
        for cid in batch:
            if cid not in by_id:
                errors += 1
                continue
            new = by_id[cid]
            existing = raw["conversations"].get(cid, {})
            aux = {k: v for k, v in existing.items() if k.startswith("_")}
            new.update(aux)
            raw["conversations"][cid] = new
            updated += 1
        if progress:
            done = i + len(batch)
            logger.info(f"  [{done}/{total}] updated={updated} errors={errors}")
        await asyncio.sleep(0.3)

    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return {"total": total, "updated": updated, "errors": errors}
