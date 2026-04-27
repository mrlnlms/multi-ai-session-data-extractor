"""Fetcher: pega arvore completa por conv via hNvQHb.

Cada conv vira 1 JSON em conversations/{uuid}.json. Paralelismo controlado por
semaphore — Google costuma tolerar 2-3 concurrent batchexecute.
"""

import asyncio
import json
from pathlib import Path

from src.extractors.gemini.api_client import GeminiAPIClient


async def fetch_conversations(
    client: GeminiAPIClient,
    conv_uuids: list[str],
    output_dir: Path,
    concurrency: int = 2,
    skip_existing: bool = True,
) -> tuple[int, int, list[tuple[str, str]]]:
    """Fetch paralelizado. Retorna (ok, skip, errors)."""
    conv_dir = output_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    ok = 0
    skip = 0
    errors: list[tuple[str, str]] = []
    done = 0
    total = len(conv_uuids)

    async def _one(uuid: str):
        nonlocal ok, skip, done
        out = conv_dir / f"{uuid}.json"
        if skip_existing and out.exists():
            async with sem:
                skip += 1
                done += 1
                if done % 20 == 0:
                    print(f"  [{done}/{total}] ok={ok} skip={skip} err={len(errors)}")
                return
        async with sem:
            try:
                conv = await client.fetch_conversation(uuid)
                if conv is None:
                    errors.append((uuid, "fetch returned None"))
                else:
                    with open(out, "w", encoding="utf-8") as f:
                        json.dump(conv, f, ensure_ascii=False)
                    ok += 1
            except Exception as e:
                errors.append((uuid, str(e)[:200]))
            done += 1
            if done % 20 == 0:
                print(f"  [{done}/{total}] ok={ok} skip={skip} err={len(errors)}")

    await asyncio.gather(*(_one(u) for u in conv_uuids))
    print(f"  [{done}/{total}] ok={ok} skip={skip} err={len(errors)} (final)")
    return ok, skip, errors
