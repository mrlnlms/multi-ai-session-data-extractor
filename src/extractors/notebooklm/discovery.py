"""Discovery: lista notebooks da conta via ub2Bae."""

import json
from pathlib import Path

from src.extractors.notebooklm.api_client import NotebookLMClient


async def discover(client: NotebookLMClient, output_dir: Path) -> list[dict]:
    """Lista todos os notebooks da conta. Salva discovery_ids.json."""
    print("Descobrindo notebooks...")
    nbs = await client.list_notebooks()
    print(f"  {len(nbs)} notebooks")

    output_dir.mkdir(parents=True, exist_ok=True)
    # Inclui timestamps pra reconciler decidir refetch vs copy
    summary = [{
        "uuid": n["uuid"],
        "title": n["title"],
        "emoji": n["emoji"],
        "update_time": n.get("update_time"),
        "create_time": n.get("create_time"),
    } for n in nbs]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return nbs
