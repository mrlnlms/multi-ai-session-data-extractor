"""Discovery Grok: lista conversas + workspaces (projects).

Persistencia eh feita pelo orchestrator APOS o fail-fast clear.
"""

import json
from pathlib import Path

from src.extractors.grok.api_client import GrokAPIClient


async def discover(client: GrokAPIClient) -> tuple[list[dict], list[dict]]:
    """Retorna (conversations, workspaces). Nao persiste.

    Cross-ref workspaces -> convs: a listagem geral retorna 'workspaces: []'
    mesmo pra convs em projects. Pra preencher, chamamos ?workspaceId={wid}
    pra cada workspace e enriquecemos a conv com '_workspace_ids'.
    """
    print("Descobrindo conversas...")
    convs = await client.list_all_conversations()
    print(f"  {len(convs)} conversations")

    print("Listando workspaces (projects)...")
    workspaces = await client.list_workspaces()
    for w in workspaces:
        wid = w.get("workspaceId")
        if not wid:
            continue
        try:
            detail = await client.get_workspace(wid)
            w["_detail"] = detail
        except Exception as e:
            w["_detail_error"] = str(e)[:200]
    print(f"  {len(workspaces)} workspaces")

    if workspaces:
        print("Cross-referenciando convs por workspace...")
        conv_to_ws: dict[str, list[str]] = {}
        for w in workspaces:
            wid = w.get("workspaceId")
            if not wid:
                continue
            token: str | None = None
            for _ in range(200):
                resp = await client.list_conversations_page(60, token, workspace_id=wid)
                for c in resp.get("conversations", []) or []:
                    cid = c.get("conversationId")
                    if cid:
                        conv_to_ws.setdefault(cid, []).append(wid)
                token = resp.get("nextPageToken") or None
                if not token:
                    break
        for c in convs:
            cid = c.get("conversationId")
            if cid and cid in conv_to_ws:
                c["_workspace_ids"] = conv_to_ws[cid]
        matched = sum(1 for c in convs if c.get("_workspace_ids"))
        print(f"  {matched} convs em workspaces")

    return convs, workspaces


def persist_discovery(
    conversations: list[dict], workspaces: list[dict], output_dir: Path
) -> None:
    """Persiste discovery_ids.json + workspaces.json. Chamar so apos fail-fast clear."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "conversationId": c["conversationId"],
            "title": c.get("title") or "",
            "modifyTime": c.get("modifyTime"),
            "createTime": c.get("createTime"),
            "starred": c.get("starred", False),
            "temporary": c.get("temporary", False),
            "workspaceIds": c.get("_workspace_ids") or [
                w.get("workspaceId") for w in (c.get("workspaces") or []) if w.get("workspaceId")
            ],
        }
        for c in conversations
        if c.get("conversationId")
    ]
    with open(output_dir / "discovery_ids.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(output_dir / "workspaces.json", "w", encoding="utf-8") as f:
        json.dump(workspaces, f, ensure_ascii=False, indent=2)
