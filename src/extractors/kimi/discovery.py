"""Discovery Kimi: lista chats + skills (oficiais + instaladas).

Persistencia eh feita pelo orchestrator APOS o fail-fast clear.
"""

import json
from pathlib import Path

from src.extractors.kimi.api_client import KimiAPIClient


async def discover(client: KimiAPIClient) -> tuple[list[dict], list[dict], list[dict]]:
    """Retorna (chats, skills_official, skills_installed). Nao persiste."""
    print("Descobrindo chats...")
    chats = await client.list_all_chats()
    print(f"  {len(chats)} chats")

    print("Listando skills (oficiais + instaladas)...")
    try:
        official = (await client.list_official_skills()).get("skills") or []
    except Exception as e:
        print(f"  warn: list_official_skills falhou: {e}")
        official = []
    try:
        installed = (await client.list_installed_skills()).get("skills") or []
    except Exception as e:
        print(f"  warn: list_installed_skills falhou: {e}")
        installed = []
    print(f"  {len(official)} oficiais, {len(installed)} instaladas")
    return chats, official, installed


def persist_discovery(
    chats: list[dict],
    skills_official: list[dict],
    skills_installed: list[dict],
    output_dir: Path,
) -> None:
    """Persiste discovery_ids.json + skills.json. Chamar so apos fail-fast clear."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "id": c["id"],
            "name": c.get("name") or "",
            "createTime": c.get("createTime"),
            "updateTime": c.get("updateTime"),
            "filesCount": len(c.get("files") or []),
        }
        for c in chats
        if c.get("id")
    ]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(output_dir / "skills.json", "w", encoding="utf-8") as f:
        json.dump(
            {"official": skills_official, "installed": skills_installed},
            f,
            ensure_ascii=False,
            indent=2,
        )
