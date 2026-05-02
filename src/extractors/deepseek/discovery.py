"""Discovery: lista sessions. Persistencia eh feita pelo orchestrator
APOS fail-fast clear — escrever antes corrompe baseline incremental se
fail-fast abortar (proxima run carrega prev_map ja com novos timestamps
e deixa de refetchar sessions que mudaram)."""

import json
from pathlib import Path

from src.extractors.deepseek.api_client import DeepSeekAPIClient


async def discover(client: DeepSeekAPIClient, output_dir: Path) -> list[dict]:
    print("Descobrindo chat sessions...")
    sessions = await client.list_conversations()
    print(f"  {len(sessions)} sessions")
    return sessions


def persist_discovery(sessions: list[dict], output_dir: Path) -> None:
    """Persiste discovery_ids.json. Chamar so apos fail-fast clear."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "id": s["id"],
            "title": s.get("title") or "",
            "updated_at": s.get("updated_at"),
            "pinned": s.get("pinned", False),
            "model_type": s.get("model_type"),
        }
        for s in sessions
    ]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
