"""Discovery: lista notebooks da conta via wXbhsf.

Lazy persist (bug preventivo #2): `discover()` so retorna a lista; persistencia
fica em `persist_discovery()` chamada pelo orchestrator APOS fail-fast. Se o
fail-fast abortar, baseline historica nao corrompe.
"""

import json
from pathlib import Path

from src.extractors.notebooklm.api_client import NotebookLMClient


async def discover(client: NotebookLMClient) -> list[dict]:
    """Lista todos os notebooks da conta. NAO persiste (lazy)."""
    print("Descobrindo notebooks...")
    nbs = await client.list_notebooks()
    print(f"  {len(nbs)} notebooks")
    return nbs


def persist_discovery(nbs: list[dict], output_dir: Path) -> None:
    """Escreve `discovery_ids.json`. Chamada APOS fail-fast pelo orchestrator."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [{
        "uuid": n["uuid"],
        "title": n["title"],
        "emoji": n["emoji"],
        "update_time": n.get("update_time"),
        "create_time": n.get("create_time"),
    } for n in nbs]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
