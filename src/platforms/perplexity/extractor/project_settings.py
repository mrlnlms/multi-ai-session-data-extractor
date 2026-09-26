"""Append-only snapshots of native Perplexity Space settings."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from uuid import UUID, uuid4

from src.platforms.perplexity.extractor.api_client import PerplexityAPIClient

HISTORY_DIR = "_project_settings"
SETTINGS_FILE = "project_settings.json"


def _encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _valid_space_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


def _validate_settings(space_uuid: str, payload: dict) -> None:
    if not _valid_space_uuid(space_uuid):
        raise ValueError("Invalid Perplexity Space UUID")
    if not isinstance(payload, dict) or payload.get("uuid") != space_uuid:
        raise ValueError("Perplexity Project settings identity mismatch")


def save_project_settings(
    raw_root: Path,
    space_uuid: str,
    slug: str,
    payload: dict,
    *,
    captured_at: datetime | None = None,
) -> Path:
    """Write one verified full-response snapshot without replacing history."""
    _validate_settings(space_uuid, payload)
    captured_at = captured_at or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        raise ValueError("Project settings capture time must be timezone-aware")
    captured_at = captured_at.astimezone(timezone.utc)
    raw_root = Path(raw_root)
    parent = raw_root / HISTORY_DIR / space_uuid
    parent.mkdir(parents=True, exist_ok=True)
    content = _encoded(payload)
    request_path = (
        "/rest/collections/get_collection?collection_slug=" + quote(slug, safe="")
        + "&version=2.18&source=default"
    )
    manifest = {
        "version": 1,
        "source": "perplexity",
        "surface": "project_settings",
        "space_uuid": space_uuid,
        "complete": True,
        "settings_complete": isinstance(payload.get("instructions"), str),
        "captured_at": captured_at.isoformat(),
        "request": {"method": "GET", "path": request_path},
        "files": {SETTINGS_FILE: {"sha256": hashlib.sha256(content).hexdigest()}},
    }
    name = f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}"
    destination = parent / name
    with TemporaryDirectory(dir=parent, prefix=".capture-") as temporary:
        stage = Path(temporary)
        (stage / SETTINGS_FILE).write_bytes(content)
        (stage / "capture.json").write_bytes(_encoded(manifest))
        stage.rename(destination)
    return destination


async def capture_project_settings(client: PerplexityAPIClient, raw_root: Path) -> dict:
    """Read current Spaces and save complete native settings snapshots."""
    try:
        collections = await client.list_user_collections()
    except Exception as exc:
        return {"discovery_succeeded": False, "targeted": 0, "captured": 0,
                "nonempty_instructions": 0,
                "errors": [{"stage": "project_discovery", "error_type": type(exc).__name__}]}

    errors: list[dict] = []
    captured = 0
    nonempty_instructions = 0
    seen: set[str] = set()
    valid = []
    for item in collections:
        space_uuid, slug = item.get("uuid"), item.get("slug")
        if not _valid_space_uuid(space_uuid) or not isinstance(slug, str) or not slug:
            errors.append({"stage": "project_discovery", "error_type": "InvalidCollectionIdentity"})
            continue
        if space_uuid in seen:
            errors.append({"stage": "project_discovery", "error_type": "DuplicateCollectionIdentity"})
            continue
        seen.add(space_uuid)
        valid.append((space_uuid, slug))

    for space_uuid, slug in valid:
        try:
            payload = await client.get_collection(slug)
            save_project_settings(raw_root, space_uuid, slug, payload)
            captured += 1
            if isinstance(payload.get("instructions"), str) and payload["instructions"]:
                nonempty_instructions += 1
        except Exception as exc:
            errors.append({"stage": "project_settings", "space_uuid": space_uuid,
                           "error_type": type(exc).__name__})
    return {"discovery_succeeded": not errors or all(
                error["stage"] != "project_discovery" for error in errors),
            "targeted": len(valid), "captured": captured,
            "nonempty_instructions": nonempty_instructions, "errors": errors}
