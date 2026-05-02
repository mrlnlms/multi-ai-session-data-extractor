"""Discovery: lista threads. Persistencia eh feita pelo orchestrator
APOS fail-fast clear — escrever antes corrompe baseline incremental se
fail-fast abortar (proxima run carrega prev_map ja com novos timestamps
e deixa de refetchar bodies que mudaram). Mesma arquitetura aplicada em
qwen/deepseek/claude_ai/gemini.
"""

import json
from pathlib import Path

from src.extractors.perplexity.api_client import PerplexityAPIClient


async def discover(client: PerplexityAPIClient, output_dir: Path) -> list[dict]:
    """Lista todas as threads. NAO persiste."""
    print("Descobrindo threads...")
    threads = await client.list_all_threads()
    print(f"  {len(threads)} threads")
    return threads


def persist_discovery(threads: list[dict], output_dir: Path) -> None:
    """Persiste discovery_ids.json + threads-index.json. Chamar so apos fail-fast clear."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "uuid": t.get("uuid"),
            "slug": t.get("slug"),
            "title": t.get("title") or "",
            "last_query_datetime": t.get("last_query_datetime"),
            "mode": t.get("mode"),
            "query_count": t.get("query_count"),
            "is_pinned": bool(t.get("is_pinned")) if t.get("is_pinned") is not None else None,
        }
        for t in threads if t.get("uuid")
    ]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    # Preserva tambem o threads-index completo (analogo ao export antigo)
    with open(output_dir / "threads-index.json", "w", encoding="utf-8") as f:
        json.dump(threads, f, ensure_ascii=False, indent=2)
