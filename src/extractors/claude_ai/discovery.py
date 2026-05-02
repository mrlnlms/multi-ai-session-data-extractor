"""Discovery: lista convs (starred + non-starred) + projects do org.

Persistencia eh feita pelo orchestrator APOS fail-fast clear — escrever
antes corrompe baseline incremental se fail-fast abortar (proxima run
carrega prev_map ja com novos timestamps e deixa de refetchar bodies que
mudaram). Mesma arquitetura aplicada em qwen/deepseek/gemini.
"""

import json
from pathlib import Path
from typing import TypedDict

from src.extractors.claude_ai.api_client import ClaudeAPIClient


class DiscoveryResult(TypedDict):
    conversations: list[dict]
    projects: list[dict]


async def discover(client: ClaudeAPIClient, output_dir: Path) -> DiscoveryResult:
    """Lista todas as convs e projects. NAO persiste."""
    print("Descobrindo conversations...")
    convs = await client.list_conversations(starred=None, limit=2000)
    print(f"  {len(convs)} conversations")

    print("Descobrindo projects...")
    projects = await client.list_projects()
    print(f"  {len(projects)} projects")

    return {"conversations": convs, "projects": projects}


def persist_discovery(disc: DiscoveryResult, output_dir: Path) -> None:
    """Persiste discovery_ids.json. Chamar so apos fail-fast clear."""
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
            for c in disc["conversations"]
        ],
        "projects": [
            {
                "uuid": p["uuid"],
                "name": p.get("name", ""),
                "updated_at": p.get("updated_at"),
                "created_at": p.get("created_at"),
                "is_starred": p.get("is_starred", False),
            }
            for p in disc["projects"]
        ],
    }
    with open(disc_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"discovery_ids.json salvo em {disc_file}")
