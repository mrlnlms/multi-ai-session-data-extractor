"""Preserve read-only ChatGPT Project details without inferring memory items."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from src.platforms.chatgpt.extractor.api_client import ChatGPTAPIClient

PROJECT_ID = re.compile(r"g-p-[A-Za-z0-9_-]+\Z")
HISTORY_DIR = "_project_settings"
DETAIL_FILE = "project_detail.json"


def _known_project_ids(raw_root: Path) -> set[str]:
    """Prior evidence broadens targets but never proves current absence."""
    ids = set()
    for root_name in (HISTORY_DIR, "project_sources"):
        root = raw_root / root_name
        if root.is_dir():
            ids.update(path.name for path in root.iterdir() if path.is_dir() and PROJECT_ID.fullmatch(path.name))
    for name in ("chatgpt_raw.json",):
        path = raw_root / name
        if not path.is_file():
            continue
        conversations = json.loads(path.read_text(encoding="utf-8")).get("conversations", {})
        values = conversations.values() if isinstance(conversations, dict) else conversations
        for conversation in values:
            if isinstance(conversation, dict):
                project_id = conversation.get("_project_id") or conversation.get("gizmo_id")
                if isinstance(project_id, str) and PROJECT_ID.fullmatch(project_id):
                    ids.add(project_id)
    return ids


def _validate_detail(project_id: str, payload: dict) -> None:
    gizmo = payload.get("gizmo") if isinstance(payload, dict) else None
    if not isinstance(gizmo, dict) or gizmo.get("id") != project_id:
        raise ValueError("Project detail identity mismatch")


def _save_detail(raw_root: Path, project_id: str, payload: dict, captured_at: datetime) -> Path:
    """Publish a complete immutable snapshot; never replace older observations."""
    if not PROJECT_ID.fullmatch(project_id):
        raise ValueError("Invalid Project ID")
    _validate_detail(project_id, payload)
    parent = raw_root / HISTORY_DIR / project_id
    parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    metadata = {
        "version": 1,
        "source": "chatgpt",
        "surface": "project_detail",
        "project_id": project_id,
        "complete": True,
        "settings_complete": (
            isinstance(payload["gizmo"].get("instructions"), str)
            and isinstance(payload["gizmo"].get("memory_scope"), str)
            and isinstance(payload["gizmo"].get("memory_enabled"), bool)
        ),
        "captured_at": captured_at.isoformat(),
        "request": {"method": "GET", "path": f"/backend-api/gizmos/{project_id}"},
        "files": {DETAIL_FILE: {"sha256": hashlib.sha256(content).hexdigest()}},
    }
    destination = parent / f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}"
    with TemporaryDirectory(dir=parent, prefix=".capture-") as staging:
        stage = Path(staging)
        (stage / DETAIL_FILE).write_bytes(content)
        (stage / "capture.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        stage.rename(destination)
    return destination


async def capture_project_settings(client: ChatGPTAPIClient, raw_root: Path) -> dict:
    """Read every discovered or known Project; failures preserve prior history."""
    known = _known_project_ids(raw_root)
    errors: list[dict] = []
    try:
        discovered = await client.list_projects()
        ids = known | {item.id for item in discovered
                       if isinstance(item.id, str) and PROJECT_ID.fullmatch(item.id)}
        discovery_succeeded = True
    except Exception as exc:
        ids = known
        discovery_succeeded = False
        errors.append({"stage": "project_discovery", "error_type": type(exc).__name__})
    captured = 0
    for project_id in sorted(ids):
        try:
            payload = await client.fetch_project_detail(project_id)
            _save_detail(raw_root, project_id, payload, datetime.now(timezone.utc))
            captured += 1
        except Exception as exc:
            # No response body or personal content in operational reports.
            errors.append({"stage": "project_detail", "project_id": project_id,
                           "error_type": type(exc).__name__})
    return {"discovery_succeeded": discovery_succeeded, "projects_targeted": len(ids),
            "projects_captured": captured, "errors": errors}
