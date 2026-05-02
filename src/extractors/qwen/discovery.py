"""Discovery: lista chats + projects. Persistencia eh feita pelo orchestrator
APOS o fail-fast clear — escrever antes corrompe a baseline incremental se o
fail-fast abortar (proxima run carrega prev_map ja com timestamps novos e
deixa de refetchar chats que mudaram)."""

import json
from pathlib import Path

from src.extractors.qwen.api_client import QwenAPIClient


async def discover(
    client: QwenAPIClient, output_dir: Path
) -> tuple[list[dict], list[dict]]:
    """Retorna (chats, projects). Nao persiste — quem chama decide quando."""
    print("Descobrindo chats...")
    chats = await client.list_all_chats()
    print(f"  {len(chats)} chats")

    print("Listando projects + files por project...")
    projects = await client.list_projects()
    # Enriquece cada project com os files (sources anexados)
    for p in projects:
        pid = p.get("id")
        if pid:
            p["_files"] = await client.list_project_files(pid)
    total_pfiles = sum(len(p.get("_files") or []) for p in projects)
    print(f"  {len(projects)} projects, {total_pfiles} project files")

    return chats, projects


def persist_discovery(chats: list[dict], projects: list[dict], output_dir: Path) -> None:
    """Persiste discovery_ids.json + projects.json. Chamar so apos fail-fast clear."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "id": c["id"],
            "title": c.get("title") or "",
            "updated_at": c.get("updated_at"),
            "created_at": c.get("created_at"),
            "pinned": c.get("pinned", False),
            "chat_type": c.get("chat_type"),
            "project_id": c.get("project_id") or None,
        }
        for c in chats
    ]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(output_dir / "projects.json", "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)
