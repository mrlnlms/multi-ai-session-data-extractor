"""Fetcher Perplexity: salva /rest/thread/{uuid} em threads/{uuid}.json."""

import json
from pathlib import Path

from src.extractors.perplexity.api_client import PerplexityAPIClient


async def fetch_threads(
    client: PerplexityAPIClient,
    uuids: list[str],
    output_dir: Path,
    skip_existing: bool = True,
) -> tuple[int, int, list[tuple[str, str]]]:
    thread_dir = output_dir / "threads"
    thread_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    skip = 0
    errors: list[tuple[str, str]] = []
    total = len(uuids)

    for i, uid in enumerate(uuids, start=1):
        out = thread_dir / f"{uid}.json"
        if skip_existing and out.exists():
            skip += 1
            if i % 20 == 0:
                print(f"  [{i}/{total}] ok={ok} skip={skip} err={len(errors)}")
            continue
        try:
            data = await client.fetch_thread(uid)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            ok += 1
        except Exception as e:
            errors.append((uid, str(e)[:200]))
        if i % 20 == 0:
            print(f"  [{i}/{total}] ok={ok} skip={skip} err={len(errors)}")
    print(f"  [{total}/{total}] ok={ok} skip={skip} err={len(errors)} (final)")
    return ok, skip, errors
