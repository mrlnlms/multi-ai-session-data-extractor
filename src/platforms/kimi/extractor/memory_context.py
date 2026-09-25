"""Cumulative raw evidence for Kimi memory and adjacent project context.

Only transport responses are captured here. Empty owner records do not provide
the native item schema needed for an AgentMemory projection yet.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from src.platforms.kimi.extractor.api_client import KimiAPIClient

logger = logging.getLogger(__name__)


def _encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _save(raw_root: Path, files: dict[str, bytes], status: dict, captured_at: datetime) -> Path:
    history = raw_root / "_memory_context" / "native"
    history.mkdir(parents=True, exist_ok=True)
    name = f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}"
    manifest = {
        "version": 1,
        "source": "kimi",
        "captured_at": captured_at.isoformat(),
        "surfaces": status,
        "files": {key: {"sha256": hashlib.sha256(data).hexdigest()} for key, data in files.items()},
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


async def _memory_pages(client: KimiAPIClient, files: dict[str, bytes]) -> dict:
    token = None
    seen_tokens: set[str] = set()
    items = 0
    for index in range(1000):
        request = {"page_size": 50}
        if token:
            request["page_token"] = token
        response = await client.list_memory_page(page_token=token)
        files[f"memory/pages/{index:04d}.json"] = _encoded({"request": request, "response": response})
        if not isinstance(response, dict) or not isinstance(response.get("memoryLimit"), int):
            raise ValueError("Malformed Kimi memory response")
        if "memories" not in response and set(response) != {"nextPageToken", "memoryLimit"}:
            raise ValueError("Unknown Kimi memory item envelope")
        batch = response.get("memories", [])
        next_token = response.get("nextPageToken")
        if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
            raise ValueError("Malformed Kimi memory items")
        if not isinstance(next_token, str):
            raise ValueError("Malformed Kimi memory cursor")
        items += len(batch)
        if not next_token:
            return {"complete": True, "items": items, "pages": index + 1}
        if not batch or next_token in seen_tokens:
            raise ValueError("Kimi memory pagination did not advance")
        seen_tokens.add(next_token)
        token = next_token
    raise ValueError("Kimi memory pagination guard exceeded")


async def _project_pages(client: KimiAPIClient, files: dict[str, bytes]) -> dict:
    token = None
    seen_tokens: set[str] = set()
    projects: dict[str, dict] = {}
    for index in range(1000):
        request = {"page_size": 100, "include_pinned": True}
        if token:
            request["page_token"] = token
        response = await client.list_projects_page(page_token=token)
        files[f"projects/pages/{index:04d}.json"] = _encoded({"request": request, "response": response})
        if not isinstance(response, dict) or not isinstance(response.get("projects"), list):
            raise ValueError("Malformed Kimi project list")
        batch = response["projects"]
        for project in batch:
            project_id = project.get("id") if isinstance(project, dict) else None
            if not isinstance(project_id, str) or not project_id or project_id in projects:
                raise ValueError("Invalid or duplicate Kimi project ID")
            projects[project_id] = project
        next_token = response.get("nextPageToken", "")
        if not isinstance(next_token, str):
            raise ValueError("Malformed Kimi project cursor")
        if not next_token:
            if len(batch) == 100:
                raise ValueError("Kimi project list may be truncated at page size")
            break
        if not batch or next_token in seen_tokens:
            raise ValueError("Kimi project pagination did not advance")
        seen_tokens.add(next_token)
        token = next_token
    else:
        raise ValueError("Kimi project pagination guard exceeded")

    for index, project_id in enumerate(projects):
        response = await client.get_project(project_id)
        files[f"projects/details/{index:04d}.json"] = _encoded(
            {"request": {"project_id": project_id}, "response": response}
        )
        if not isinstance(response, dict) or not isinstance(response.get("project"), dict):
            raise ValueError("Malformed Kimi project detail")
        if response["project"].get("id") != project_id:
            raise ValueError("Kimi project detail ID mismatch")
    return {"complete": True, "projects": len(projects), "details": len(projects)}


async def capture_memory_context(client: KimiAPIClient, raw_root: Path) -> dict:
    """Save independent read surfaces; a failure never implies deletion."""
    captured_at = datetime.now(timezone.utc)
    files: dict[str, bytes] = {}
    status: dict[str, dict] = {}
    for surface, operation in (
        ("account_memory", lambda: _memory_pages(client, files)),
        ("user_setting_read", client.get_user_setting),
        ("dream_status", client.get_dream_status),
        ("project_catalog", lambda: _project_pages(client, files)),
    ):
        try:
            result = await operation()
            if surface == "user_setting_read":
                files["account/user_setting.json"] = _encoded(result)
                if not isinstance(result, dict) or not isinstance(result.get("userSetting"), dict):
                    raise ValueError("Malformed Kimi user setting")
                status[surface] = {"complete": True}
            elif surface == "dream_status":
                files["account/dream_status.json"] = _encoded(result)
                if (not isinstance(result, dict) or not isinstance(result.get("dreamVault"), dict)
                        or not isinstance(result.get("featureAvailable"), bool)):
                    raise ValueError("Malformed Kimi dream status")
                status[surface] = {"complete": True}
            else:
                status[surface] = result
        except Exception as exc:
            logger.warning("Kimi %s read incomplete (%s)", surface, type(exc).__name__)
            status[surface] = {"complete": False, "error_type": type(exc).__name__}
    snapshot = _save(Path(raw_root), files, status, captured_at)
    return {"surfaces": status, "snapshot": snapshot}
