"""Fetcher Qwen: pega conversa full e salva em conversations/{id}.json."""

import json
from pathlib import Path

from src.extractors.qwen.api_client import QwenAPIClient


async def fetch_conversations(
    client: QwenAPIClient,
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
            if not data.get("success", False):
                errors.append((cid, f"api success=false: {json.dumps(data.get('data', {}))[:200]}"))
                continue
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            ok += 1
        except Exception as e:
            errors.append((cid, str(e)[:200]))
        if i % 20 == 0:
            print(f"  [{i}/{total}] ok={ok} skip={skip} err={len(errors)}")
    print(f"  [{total}/{total}] ok={ok} skip={skip} err={len(errors)} (final)")
    return ok, skip, errors
