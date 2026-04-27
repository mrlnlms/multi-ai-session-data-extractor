"""Fetcher: pega history_messages de cada conv e salva em conversations/{id}.json.

Nao paraleliza via semaphore porque cada request usa a mesma page — Playwright
nao serializa bem eval concurrent. Sequential e rapido o suficiente (~1 req/s).
"""

import json
from pathlib import Path

from src.extractors.deepseek.api_client import DeepSeekAPIClient


async def fetch_conversations(
    client: DeepSeekAPIClient,
    conv_ids: list[str],
    output_dir: Path,
    skip_existing: bool = True,
) -> tuple[int, int, list[tuple[str, str]]]:
    conv_dir = output_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    skip = 0
    errors: list[tuple[str, str]] = []
    total = len(conv_ids)

    for i, cid in enumerate(conv_ids, start=1):
        out = conv_dir / f"{cid}.json"
        if skip_existing and out.exists():
            skip += 1
            if i % 20 == 0:
                print(f"  [{i}/{total}] ok={ok} skip={skip} err={len(errors)}")
            continue
        try:
            data = await client.fetch_conversation(cid)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            ok += 1
        except Exception as e:
            errors.append((cid, str(e)[:200]))
        if i % 20 == 0:
            print(f"  [{i}/{total}] ok={ok} skip={skip} err={len(errors)}")
    print(f"  [{total}/{total}] ok={ok} skip={skip} err={len(errors)} (final)")
    return ok, skip, errors
