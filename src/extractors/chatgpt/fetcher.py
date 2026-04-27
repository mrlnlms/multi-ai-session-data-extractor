"""Fetcher — baixa conteudo de convs em batches, com progresso e throttle."""

import asyncio
import logging
from typing import Callable

from src.extractors.chatgpt.api_client import ChatGPTAPIClient

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
THROTTLE_SECONDS = 3


async def fetch_all(
    client: ChatGPTAPIClient,
    ids: list[str],
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict]:
    """Fetch content de todas as convs em batches.

    Args:
        client: ChatGPTAPIClient.
        ids: lista de conversation IDs.
        on_progress: callback (fetched_count, total) a cada batch concluido.

    Returns:
        dict mapeando conv_id -> raw dict.
    """
    results: dict[str, dict] = {}
    total = len(ids)

    for start in range(0, total, BATCH_SIZE):
        batch_ids = ids[start : start + BATCH_SIZE]
        try:
            batch_raws = await client.fetch_conversations_batch(batch_ids)
            for raw in batch_raws:
                if "id" in raw:
                    results[raw["id"]] = raw
        except Exception as exc:
            logger.error(f"Batch {start}:{start+len(batch_ids)} falhou: {exc}")
            # Fallback: tenta single por single
            for cid in batch_ids:
                try:
                    results[cid] = await client.fetch_conversation(cid)
                except Exception as single_exc:
                    logger.error(f"Single fetch de {cid} falhou: {single_exc}")

        if on_progress:
            on_progress(len(results), total)

        # Throttle preventivo (exceto no ultimo)
        if start + BATCH_SIZE < total:
            await asyncio.sleep(THROTTLE_SECONDS)

    return results
