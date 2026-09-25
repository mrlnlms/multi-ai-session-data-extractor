"""Immutable snapshots of Perplexity's account Memory GraphQL collection."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from src.platforms.perplexity.extractor.api_client import MEMORY_QUERY_HASH, PerplexityAPIClient

logger = logging.getLogger(__name__)


def _encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _page(payload: dict) -> tuple[str, list[dict], dict]:
    if payload.get("errors"):
        raise ValueError("Perplexity memory GraphQL reported errors")
    try:
        scope = payload["data"]["viewer"]["knowledgeContext"]["scopeByKind"]
        categories = scope["memoryCategories"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed Perplexity memory scope") from exc
    if not isinstance(scope.get("id"), str) or not scope["id"] or not isinstance(categories, list):
        raise ValueError("Malformed Perplexity memory category list")
    nodes: list[dict] = []
    page_info: dict | None = None
    category_ids: set[str] = set()
    for category in categories:
        if (not isinstance(category, dict) or not isinstance(category.get("id"), str)
                or not category["id"].startswith("individual:")):
            raise ValueError("Malformed Perplexity memory category")
        if category["id"] in category_ids:
            raise ValueError("Duplicate Perplexity memory category")
        category_ids.add(category["id"])
        items = category.get("items")
        if not isinstance(items, dict) or items.get("status") != "OK":
            raise ValueError("Incomplete Perplexity memory category")
        edges, info = items.get("edges"), items.get("pageInfo")
        if not isinstance(edges, list) or not isinstance(info, dict) or not isinstance(info.get("hasNextPage"), bool):
            raise ValueError("Malformed Perplexity memory pagination")
        if page_info is not None and info != page_info:
            raise ValueError("Independent category cursors need separate pagination")
        page_info = info
        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
                raise ValueError("Perplexity memory item lacks native ID")
            if not isinstance(node.get("displayValue"), str):
                raise ValueError("Perplexity memory item lacks display value")
            if node.get("categoryId") != category["id"]:
                raise ValueError("Perplexity memory item has mismatched category")
            nodes.append(node)
    if page_info is None:
        raise ValueError("Perplexity memory has no category pagination")
    return scope["id"], nodes, page_info


def _save(raw_root: Path, files: dict[str, bytes], *, captured_at: datetime,
          complete: bool, error: str | None) -> Path:
    history = raw_root / "_account_memory" / "native"
    history.mkdir(parents=True, exist_ok=True)
    name = f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}"
    manifest = {
        "version": 1, "source": "perplexity", "surface": "account_memory_graphql",
        "captured_at": captured_at.isoformat(), "complete": complete, "error_type": error,
        "query": {"operationName": "KnowledgeContextKnowledgeRelayQuery",
                  "persistedQueryHash": MEMORY_QUERY_HASH, "pageSize": 100},
        "files": {key: {"sha256": hashlib.sha256(value).hexdigest()} for key, value in files.items()},
    }
    with TemporaryDirectory(dir=history, prefix=".capture-") as temporary:
        stage = Path(temporary)
        for relative, data in files.items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (stage / "capture.json").write_bytes(_encoded(manifest))
        stage.rename(history / name)
    return history / name


async def capture_account_memory(client: PerplexityAPIClient, raw_root: Path) -> dict:
    """Fetch every page; partial observations never imply disappearance."""
    captured_at = datetime.now(timezone.utc)
    files: dict[str, bytes] = {}
    cursor = None
    seen_cursors: set[str] = set()
    seen_ids: set[str] = set()
    scope_id = None
    error = None
    try:
        for index in range(1000):
            payload = await client.list_account_memory_page(after=cursor)
            files[f"pages/{index:04d}.json"] = _encoded({"after": cursor, "response": payload})
            observed_scope, nodes, info = _page(payload)
            if scope_id is not None and observed_scope != scope_id:
                raise ValueError("Perplexity memory scope changed during pagination")
            scope_id = observed_scope
            for node in nodes:
                if node["id"] in seen_ids:
                    raise ValueError("Duplicate Perplexity memory ID across pages")
                seen_ids.add(node["id"])
            if not info["hasNextPage"]:
                break
            cursor = info.get("endCursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise ValueError("Perplexity memory cursor did not advance")
            seen_cursors.add(cursor)
        else:
            raise ValueError("Perplexity memory exceeded pagination guard")
    except Exception as exc:
        error = type(exc).__name__
        logger.warning("Perplexity memory capture incomplete (%s)", error)
    snapshot = _save(Path(raw_root), files, captured_at=captured_at, complete=error is None, error=error)
    return {"complete": error is None, "items": len(seen_ids), "pages": len(files),
            "error_type": error, "snapshot": snapshot}
