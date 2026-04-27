"""Discovery: lista convs (starred + non-starred) + projects do org.

Salva em discovery_ids.json pra o fetcher usar depois.
"""

import json
from pathlib import Path
from typing import TypedDict

from src.extractors.claude_ai.api_client import ClaudeAPIClient


class DiscoveryResult(TypedDict):
    conversations: list[dict]
    projects: list[dict]


async def discover(client: ClaudeAPIClient, output_dir: Path) -> DiscoveryResult:
    """Lista todas as convs e projects. Salva discovery_ids.json pro caller."""
    print("Descobrindo conversations...")
    convs = await client.list_conversations(starred=None, limit=2000)
    print(f"  {len(convs)} conversations")

    print("Descobrindo projects...")
    projects = await client.list_projects()
    print(f"  {len(projects)} projects")

    output_dir.mkdir(parents=True, exist_ok=True)
    disc_file = output_dir / "discovery_ids.json"

    # Versao enxuta pra o fetcher: so uuid + timestamps pra cutoff incremental
    summary = {
        "conversations": [
            {
                "uuid": c["uuid"],
                "name": c.get("name", ""),
                "updated_at": c.get("updated_at"),
                "created_at": c.get("created_at"),
                "is_starred": c.get("is_starred", False),
                "project_uuid": c.get("project_uuid"),
            }
            for c in convs
        ],
        "projects": [
            {
                "uuid": p["uuid"],
                "name": p.get("name", ""),
                "updated_at": p.get("updated_at"),
                "created_at": p.get("created_at"),
                "is_starred": p.get("is_starred", False),
            }
            for p in projects
        ],
    }
    with open(disc_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"discovery_ids.json salvo em {disc_file}")
    return {"conversations": convs, "projects": projects}
