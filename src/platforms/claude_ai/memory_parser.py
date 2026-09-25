"""Project verified Claude account and project topics into versioned memory tables."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from src.parsing.agent_memory import AgentMemoryParseResult
from src.schema.models import AgentMemory, AgentMemoryTemporalEvidence, AgentMemoryVersion


def _digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _time(value: object) -> pd.Timestamp | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = pd.to_datetime(value, utc=True)
        return None if pd.isna(result) else result
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass
class _Observation:
    key: str
    kind: str
    content: str
    locator: str
    captured_at: pd.Timestamp | None
    updated_at: pd.Timestamp | None
    project_key: str | None
    name: str | None
    description: str | None
    native: dict


def _capture(raw_root: Path, manifest_path: Path) -> tuple[pd.Timestamp, list[_Observation]] | None:
    metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    if metadata.get("complete") is False:
        return None
    if metadata.get("version") != 1 or metadata.get("source") != "claude_ai" or metadata.get("surface") != "melange":
        raise ValueError("Unsupported Claude memory snapshot provenance")
    captured = _time(metadata.get("captured_at"))
    if captured is None:
        raise ValueError("Claude memory snapshot has no valid capture time")
    files = metadata.get("files")
    if not isinstance(files, dict) or "list.json" not in files:
        raise ValueError("Claude memory snapshot lacks its listing")
    for name, info in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not isinstance(info, dict):
            raise ValueError("Invalid Claude memory snapshot file")
        if _digest((manifest_path.parent / relative).read_bytes()) != info.get("sha256"):
            raise ValueError("Claude memory snapshot hash mismatch")
    listing = json.loads((manifest_path.parent / "list.json").read_bytes())
    if not isinstance(listing, dict) or not isinstance(listing.get("data"), list):
        raise ValueError("Malformed Claude memory listing")
    observations = []
    seen_ids, seen_paths = set(), set()
    for item in listing["data"]:
        if not isinstance(item, dict):
            raise ValueError("Malformed Claude memory listing item")
        native_id, path = item.get("memory_id"), item.get("path")
        if not isinstance(native_id, str) or not native_id or not isinstance(path, str) or not path:
            raise ValueError("Claude memory topic lacks native ID or path")
        if native_id in seen_ids or path in seen_paths:
            raise ValueError("Duplicate Claude memory topic")
        seen_ids.add(native_id)
        seen_paths.add(path)
        item_file = f"items/{_digest(path)}.json"
        if item_file not in files:
            raise ValueError("Complete Claude memory snapshot lacks a topic read")
        read = json.loads((manifest_path.parent / item_file).read_bytes())
        if not isinstance(read, dict) or read.get("path") != path or not isinstance(read.get("content"), str):
            raise ValueError("Malformed Claude memory topic read")
        parts = path.split("/")
        is_project = item.get("category_id") == "projects"
        if is_project and (len(parts) < 4 or parts[1] != "projects" or not parts[2]):
            raise ValueError("Claude project memory lacks project scope")
        updated = _time(read.get("updated_at")) or _time(item.get("updated_at"))
        locator = (manifest_path.parent / item_file).relative_to(raw_root).as_posix()
        observations.append(_Observation(
            key=native_id, kind="project_memory" if is_project else "saved_memory",
            content=read["content"], locator=locator, captured_at=captured,
            updated_at=updated, project_key=parts[2] if is_project else None,
            name=item.get("display_name") if isinstance(item.get("display_name"), str) else None,
            description=item.get("description") if isinstance(item.get("description"), str) else None,
            native={"list": item, "read": {key: value for key, value in read.items() if key not in {"content", "parsed"}}},
        ))
    return captured, observations


def parse_account_memory(raw_root: Path, account_id: str | None) -> AgentMemoryParseResult:
    raw_root = Path(raw_root)
    manifests = sorted((raw_root / "_account_memory" / "melange").glob("*/capture.json"))
    legacy = raw_root / "claude_ai_memory.md"
    if not manifests and not legacy.is_file():
        return AgentMemoryParseResult([], [], [])
    if account_id is None:
        raise ValueError("Account UUID is required to project Claude memories")

    captures = [result for path in manifests if not path.parent.name.startswith(".")
                if (result := _capture(raw_root, path)) is not None]
    captures.sort(key=lambda item: item[0])
    latest_keys = {item.key for item in captures[-1][1]} if captures else None
    observations = [item for _, items in captures for item in items]
    if legacy.is_file():
        content = legacy.read_text(encoding="utf-8")
        observations.append(_Observation(
            key=f"legacy_export/{_digest(content)}", kind="legacy_export", content=content,
            locator=legacy.relative_to(raw_root).as_posix(), captured_at=None,
            updated_at=None, project_key=None, name=None, description=None, native={},
        ))

    grouped: dict[str, list[_Observation]] = {}
    for item in observations:
        grouped.setdefault(item.key, []).append(item)
    memories, versions, evidence = [], [], {}
    for key, items in sorted(grouped.items()):
        items.sort(key=lambda item: (item.captured_at or pd.Timestamp.min.tz_localize("UTC"), item.locator))
        memory_id = f"claude_ai:{account_id}:{quote(key, safe='')}"
        by_hash: dict[str, list[_Observation]] = {}
        for item in items:
            by_hash.setdefault(_digest(item.content), []).append(item)
        selected = None
        for digest, observed in sorted(by_hash.items()):
            version_id = f"{memory_id}:{digest}"
            observed_times = [item.captured_at for item in observed if item.captured_at is not None]
            first_seen = min(observed_times) if observed_times else None
            last_seen = max(observed_times) if observed_times else None
            updates = [item.updated_at for item in observed if item.updated_at is not None]
            native_updated = max(updates) if updates else None
            version = AgentMemoryVersion(
                version_id=version_id, memory_id=memory_id, source="claude_ai", account_id=account_id,
                relative_path=observed[0].locator, content_sha256=digest, content=observed[0].content,
                content_size=len(observed[0].content.encode("utf-8")), source_modified_at=native_updated,
                source_birth_at=None, first_seen_at=first_seen, last_seen_at=last_seen,
                captured_at=first_seen, effective_created_at=first_seen,
                effective_updated_at=native_updated or last_seen,
                created_at_basis="first_observed" if first_seen is not None else None,
                updated_at_basis="native_updated_at" if native_updated is not None else ("last_observed" if last_seen is not None else None),
                created_at_confidence="high" if first_seen is not None else "unknown",
                updated_at_confidence="high" if native_updated is not None or last_seen is not None else "unknown",
            )
            versions.append(version)
            if digest == _digest(items[-1].content):
                selected = version
            for item in observed:
                temporal = [("capture_observed" if item.captured_at is not None else "legacy_export", item.captured_at)]
                if item.updated_at is not None:
                    temporal.append(("native_updated_at", item.updated_at))
                for evidence_type, timestamp in temporal:
                    evidence_id = _digest(_json([version_id, evidence_type, timestamp.isoformat() if timestamp is not None else None, item.locator]))
                    evidence[evidence_id] = AgentMemoryTemporalEvidence(
                        evidence_id=evidence_id, memory_id=memory_id, version_id=version_id,
                        source="claude_ai", account_id=account_id, evidence_type=evidence_type,
                        timestamp=timestamp, confidence="high" if timestamp is not None else "unknown",
                        locator=item.locator, details_json=_json(item.native), is_inference=False,
                    )
        assert selected is not None
        current = items[-1]
        seen = [item.captured_at for item in items if item.captured_at is not None]
        memories.append(AgentMemory(
            memory_id=memory_id, source="claude_ai", account_id=account_id,
            project_path=None, project_key=current.project_key,
            file_name=Path(current.locator).name, name=current.name, description=current.description,
            kind=current.kind, content=current.content,
            content_size=len(current.content.encode("utf-8")),
            created_at=selected.effective_created_at, updated_at=selected.effective_updated_at,
            relative_path=current.locator, current_version_id=selected.version_id,
            first_seen_at=min(seen) if seen else None, last_seen_at=max(seen) if seen else None,
            is_preserved_missing=current.kind != "legacy_export" and latest_keys is not None and key not in latest_keys,
        ))
    return AgentMemoryParseResult(memories, sorted(versions, key=lambda item: item.version_id),
                                  [evidence[key] for key in sorted(evidence)])
