"""Discovery: lista convs via MaZiqc e salva discovery_ids.json."""

import json
from pathlib import Path

from src.extractors.gemini.api_client import GeminiAPIClient


async def discover(client: GeminiAPIClient, output_dir: Path) -> list[dict]:
    """Lista todas as convs do account. Salva discovery_ids.json."""
    print("Descobrindo conversations...")
    convs = await client.list_conversations()
    print(f"  {len(convs)} conversations")

    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "uuid": c["uuid"],
            "title": c["title"],
            "created_at_secs": c["created_at_secs"],
        }
        for c in convs
    ]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return convs
