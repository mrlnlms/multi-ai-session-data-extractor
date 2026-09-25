"""Immutable, independent Qwen account memory and personalization reads."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from src.platforms.qwen.extractor.api_client import QwenAPIClient

logger = logging.getLogger(__name__)
PAGE_SIZE = 50


def _encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _memory_page(payload: dict) -> tuple[list[dict], int]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Qwen memory response was not successful")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Qwen memory response has no data object")
    nodes, total = data.get("memory_nodes"), data.get("total")
    if not isinstance(nodes, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError("Malformed Qwen memory page")
    for node in nodes:
        if (not isinstance(node, dict)
                or not isinstance(node.get("memory_node_id"), str) or not node["memory_node_id"]
                or not isinstance(node.get("content"), str)
                or not isinstance(node.get("chat_id"), str)
                or any(not isinstance(node.get(key), int) or isinstance(node.get(key), bool)
                       for key in ("created_at", "updated_at"))):
            raise ValueError("Malformed Qwen memory node")
    return nodes, total


def _save(raw_root: Path, surface: str, files: dict[str, bytes], captured_at: datetime,
          *, complete: bool, error_type: str | None) -> Path:
    history = raw_root / "_account_memory" / "native" / surface
    history.mkdir(parents=True, exist_ok=True)
    name = f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}"
    manifest = {
        "version": 1, "source": "qwen", "surface": surface,
        "captured_at": captured_at.isoformat(), "complete": complete,
        "error_type": error_type,
        "files": {key: {"sha256": hashlib.sha256(data).hexdigest()}
                  for key, data in files.items()},
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


async def capture_account_memory(client: QwenAPIClient, raw_root: Path) -> dict:
    """Capture full paginated reads; incomplete reads never imply deletion."""
    result = {}
    for surface in ("saved_memories", "personalization"):
        captured_at = datetime.now(timezone.utc)
        files: dict[str, bytes] = {}
        error_type = None
        item_count = 0
        try:
            if surface == "saved_memories":
                seen: set[str] = set()
                expected_total = None
                for page_num in range(1, 1001):
                    payload = await client.list_memory_page(page_num, PAGE_SIZE)
                    files[f"pages/{page_num:04d}.json"] = _encoded({
                        "request": {"page_size": PAGE_SIZE, "page_num": page_num},
                        "response": payload,
                    })
                    nodes, total = _memory_page(payload)
                    if expected_total is None:
                        expected_total = total
                    if total != expected_total or len(nodes) > PAGE_SIZE:
                        raise ValueError("Qwen memory pagination changed or exceeded page size")
                    for node in nodes:
                        native_id = node["memory_node_id"]
                        if native_id in seen:
                            raise ValueError("Duplicate Qwen memory ID across pages")
                        seen.add(native_id)
                    item_count = len(seen)
                    if item_count == total:
                        break
                    if not nodes or len(nodes) != PAGE_SIZE or item_count > total:
                        raise ValueError("Incomplete Qwen memory pagination")
                else:
                    raise ValueError("Qwen memory pagination guard exceeded")
            else:
                payload = await client.get_user_settings()
                files["settings.json"] = _encoded(payload)
                data = payload.get("data") if isinstance(payload, dict) else None
                if (payload.get("success") is not True or not isinstance(data, dict)
                        or not isinstance(data.get("memory"), dict)
                        or ("personalization" in data and
                            data["personalization"] is not None and
                            not isinstance(data["personalization"], dict))):
                    raise ValueError("Malformed Qwen user settings")
                item_count = int(bool(data.get("personalization")))
        except Exception as exc:
            error_type = type(exc).__name__
            logger.warning("Qwen %s read incomplete (%s)", surface, error_type)
        snapshot = _save(Path(raw_root), surface, files, captured_at,
                         complete=error_type is None, error_type=error_type)
        result[surface] = {
            "complete": error_type is None, "items": item_count,
            "error_type": error_type, "snapshot": snapshot,
        }
    return result
