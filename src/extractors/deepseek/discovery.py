"""Discovery: lista sessions e salva discovery_ids.json."""

import json
from pathlib import Path

from src.extractors.deepseek.api_client import DeepSeekAPIClient


async def discover(client: DeepSeekAPIClient, output_dir: Path) -> list[dict]:
    print("Descobrindo chat sessions...")
    sessions = await client.list_conversations()
    print(f"  {len(sessions)} sessions")

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
    return sessions
