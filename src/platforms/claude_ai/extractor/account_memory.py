"""Capture Claude's native account/project memory topics without flattening them."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from src.platforms.claude_ai.extractor.api_client import ClaudeAPIClient

logger = logging.getLogger(__name__)


def _encoded(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _validate_listing(payload: object) -> list[dict]:
    if (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)
            or not isinstance(payload.get("categories"), list)):
        raise ValueError("Malformed Claude memory listing")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for item in payload["data"]:
        if not isinstance(item, dict):
            raise ValueError("Malformed Claude memory listing item")
        native_id, path = item.get("memory_id"), item.get("path")
        if not isinstance(native_id, str) or not native_id or not isinstance(path, str) or not path:
            raise ValueError("Claude memory item lacks native identity or path")
        if native_id in seen_ids or path in seen_paths:
            raise ValueError("Duplicate Claude memory identity or path")
        seen_ids.add(native_id)
        seen_paths.add(path)
    return payload["data"]


def _item_filename(path: str) -> str:
    return f"items/{hashlib.sha256(path.encode('utf-8')).hexdigest()}.json"


def _save_snapshot(raw_root: Path, files: dict[str, bytes], *, complete: bool, captured_at: datetime) -> Path:
    history = raw_root / "_account_memory" / "melange"
    history.mkdir(parents=True, exist_ok=True)
    name = f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}"
    metadata = {
        "version": 1,
        "source": "claude_ai",
        "surface": "melange",
        "captured_at": captured_at.isoformat(),
        "complete": complete,
        "requests": {"list": {"method": "POST", "path": "/melange/list", "json": {}},
                     "read": {"method": "POST", "path": "/melange/read", "json": {"path": "<item path>"}}},
        "files": {name: {"sha256": hashlib.sha256(content).hexdigest()} for name, content in files.items()},
    }
    with TemporaryDirectory(dir=history, prefix=".capture-") as temporary:
        stage = Path(temporary)
        for relative, content in files.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        (stage / "capture.json").write_bytes(_encoded(metadata))
        stage.rename(history / name)
    return history / name


async def capture_account_memory(client: ClaudeAPIClient, raw_root: Path) -> dict:
    """Archive a complete list and every read response as one dated observation.

    A failed read creates an incomplete diagnostic capture. The parser never
    treats it as an empty list or evidence that an older topic disappeared.
    The previous classic Markdown export is intentionally left untouched.
    """
    captured_at = datetime.now(timezone.utc)
    listing = await client.list_memory_topics()
    entries = _validate_listing(listing)
    files = {"list.json": _encoded(listing)}
    settings_error = None
    mode_is_melange = False
    try:
        settings = await client.get_memory_settings()
        if not isinstance(settings, dict):
            raise ValueError("Malformed Claude memory settings")
        mode_is_melange = settings.get("memory_mode") == "melange"
        files["settings.json"] = _encoded(settings)
    except Exception as exc:
        settings_error = type(exc).__name__
        logger.warning("Claude memory settings capture failed (%s)", settings_error)

    semaphore = asyncio.Semaphore(4)

    async def read_one(entry: dict) -> tuple[str, bytes | None]:
        async with semaphore:
            try:
                item = await client.read_memory_topic(entry["path"])
                if not isinstance(item, dict) or item.get("path") != entry["path"] or not isinstance(item.get("content"), str):
                    raise ValueError("Malformed Claude memory read response")
                return _item_filename(entry["path"]), _encoded(item)
            except Exception as exc:
                logger.warning("Claude memory topic read failed (%s)", type(exc).__name__)
                return _item_filename(entry["path"]), None

    reads = await asyncio.gather(*(read_one(entry) for entry in entries))
    failed = sum(content is None for _, content in reads)
    files.update({name: content for name, content in reads if content is not None})
    # A mode change or missing settings must not turn an empty Melange list
    # into apparent deletion of previously captured native topics.
    complete = failed == 0 and mode_is_melange
    snapshot = _save_snapshot(raw_root, files, complete=complete, captured_at=captured_at)
    return {"complete": complete, "topics": len(entries), "failed_reads": failed,
            "settings_error": settings_error, "snapshot": snapshot}
