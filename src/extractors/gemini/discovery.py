"""Discovery: lista convs via MaZiqc. Persistencia eh feita pelo orchestrator
APOS fail-fast clear — escrever antes corrompe baseline incremental se
fail-fast abortar (proxima run carrega prev_map ja com novos timestamps
e deixa de refetchar bodies que mudaram)."""

import json
from pathlib import Path

from src.extractors.gemini.api_client import GeminiAPIClient


async def discover(client: GeminiAPIClient, output_dir: Path) -> list[dict]:
    """Lista todas as convs do account. NAO persiste."""
    print("Descobrindo conversations...")
    convs = await client.list_conversations()
    print(f"  {len(convs)} conversations")
    return convs


def persist_discovery(convs: list[dict], output_dir: Path) -> None:
    """Persiste discovery_ids.json. Chamar so apos fail-fast clear."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "uuid": c["uuid"],
            "title": c["title"],
            "pinned": c.get("pinned", False),
            "created_at_secs": c["created_at_secs"],
        }
        for c in convs
    ]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
