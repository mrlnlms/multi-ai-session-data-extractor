"""Replay verified Perplexity account Memory pages into canonical versions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import pandas as pd

from src.parsing.agent_memory import AgentMemoryParseResult
from src.platforms.perplexity.extractor.account_memory import _page
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
    native_id: str
    content: str
    name: str | None
    locator: str
    captured_at: pd.Timestamp
    updated_at: pd.Timestamp | None
    native: dict


def _capture(raw_root: Path, manifest_path: Path) -> tuple[pd.Timestamp, list[_Observation]] | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("complete") is False:
        return None
    if manifest.get("complete") is not True:
        raise ValueError("Perplexity memory snapshot has no completeness attestation")
    if (manifest.get("version") != 1 or manifest.get("source") != "perplexity"
            or manifest.get("surface") != "account_memory_graphql"):
        raise ValueError("Unsupported Perplexity memory snapshot provenance")
    captured = _time(manifest.get("captured_at"))
    if captured is None:
        raise ValueError("Perplexity memory snapshot has no valid capture time")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Complete Perplexity memory snapshot has no pages")
    for name, info in files.items():
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or not name.startswith("pages/")
                or not isinstance(info, dict)):
            raise ValueError("Invalid Perplexity memory snapshot file")
        if _digest((manifest_path.parent / relative).read_bytes()) != info.get("sha256"):
            raise ValueError("Perplexity memory snapshot hash mismatch")
    observations: list[_Observation] = []
    seen: set[str] = set()
    prior_cursor = None
    scope_id = None
    names = sorted(files)
    for index, name in enumerate(names):
        if name != f"pages/{index:04d}.json":
            raise ValueError("Perplexity memory pages are not consecutive")
        wrapper = json.loads((manifest_path.parent / name).read_bytes())
        if not isinstance(wrapper, dict) or wrapper.get("after") != prior_cursor:
            raise ValueError("Perplexity memory page cursor mismatch")
        payload = wrapper.get("response")
        if not isinstance(payload, dict):
            raise ValueError("Malformed Perplexity memory page")
        current_scope, nodes, info = _page(payload)
        if scope_id is not None and current_scope != scope_id:
            raise ValueError("Perplexity memory scope changed across pages")
        scope_id = current_scope
        categories = payload["data"]["viewer"]["knowledgeContext"]["scopeByKind"]["memoryCategories"]
        for category_index, category in enumerate(categories):
            for edge_index, edge in enumerate(category["items"]["edges"]):
                node = edge["node"]
                native_id = node["id"]
                if native_id in seen:
                    raise ValueError("Duplicate Perplexity memory ID")
                seen.add(native_id)
                name_value = node.get("displayKeyPretty") or node.get("displayKey")
                locator = ((manifest_path.parent / name).relative_to(raw_root).as_posix()
                           + f"#/response/data/viewer/knowledgeContext/scopeByKind/memoryCategories/{category_index}/items/edges/{edge_index}/node")
                observations.append(_Observation(
                    native_id=native_id, content=node["displayValue"],
                    name=name_value if isinstance(name_value, str) else None,
                    locator=locator, captured_at=captured,
                    updated_at=_time(node.get("updatedAt")), native=node,
                ))
        if len(nodes) != sum(len(c["items"]["edges"]) for c in categories):
            raise ValueError("Perplexity memory page item mismatch")
        if info["hasNextPage"]:
            prior_cursor = info.get("endCursor")
            if not isinstance(prior_cursor, str) or not prior_cursor or index == len(names) - 1:
                raise ValueError("Incomplete Perplexity memory pagination")
        elif index != len(names) - 1:
            raise ValueError("Perplexity memory has pages after terminal cursor")
    return captured, observations


def parse_account_memory(raw_root: Path, account_id: str | None) -> AgentMemoryParseResult:
    raw_root = Path(raw_root)
    manifests = sorted((raw_root / "_account_memory" / "native").glob("*/capture.json"))
    if not manifests:
        return AgentMemoryParseResult([], [], [])
    if account_id is None:
        raise ValueError("Account UUID is required to project Perplexity memories")
    captures = [result for path in manifests if not path.parent.name.startswith(".")
                if (result := _capture(raw_root, path)) is not None]
    captures.sort(key=lambda item: item[0])
    latest_ids = {item.native_id for item in captures[-1][1]} if captures else None
    grouped: dict[str, list[_Observation]] = {}
    for _, items in captures:
        for item in items:
            grouped.setdefault(item.native_id, []).append(item)
    memories: list[AgentMemory] = []
    versions: list[AgentMemoryVersion] = []
    evidence: dict[str, AgentMemoryTemporalEvidence] = {}
    for native_id, items in sorted(grouped.items()):
        items.sort(key=lambda item: (item.captured_at, item.locator))
        memory_id = f"perplexity:{account_id}:{quote(native_id, safe='')}"
        by_hash: dict[str, list[_Observation]] = {}
        for item in items:
            by_hash.setdefault(_digest(item.content), []).append(item)
        current_hash = _digest(items[-1].content)
        selected = None
        for content_hash, observed in sorted(by_hash.items()):
            version_id = f"{memory_id}:{content_hash}"
            first_seen = min(item.captured_at for item in observed)
            last_seen = max(item.captured_at for item in observed)
            updates = [item.updated_at for item in observed if item.updated_at is not None]
            native_updated = max(updates) if updates else None
            version = AgentMemoryVersion(
                version_id=version_id, memory_id=memory_id, source="perplexity", account_id=account_id,
                relative_path=observed[0].locator, content_sha256=content_hash,
                content=observed[0].content, content_size=len(observed[0].content.encode("utf-8")),
                source_modified_at=native_updated, source_birth_at=None,
                first_seen_at=first_seen, last_seen_at=last_seen, captured_at=first_seen,
                effective_created_at=first_seen, effective_updated_at=native_updated or last_seen,
                created_at_basis="first_observed",
                updated_at_basis="native_updated_at" if native_updated is not None else "last_observed",
                created_at_confidence="high", updated_at_confidence="high",
            )
            versions.append(version)
            if content_hash == current_hash:
                selected = version
            for item in observed:
                for evidence_type, timestamp in (("capture_observed", item.captured_at),
                                                 ("native_updated_at", item.updated_at)):
                    if timestamp is None:
                        continue
                    evidence_id = _digest(_json([version_id, evidence_type, timestamp.isoformat(), item.locator]))
                    evidence[evidence_id] = AgentMemoryTemporalEvidence(
                        evidence_id=evidence_id, memory_id=memory_id, version_id=version_id,
                        source="perplexity", account_id=account_id, evidence_type=evidence_type,
                        timestamp=timestamp, confidence="high", locator=item.locator,
                        details_json=_json(item.native), is_inference=False,
                    )
        assert selected is not None
        current = items[-1]
        memories.append(AgentMemory(
            memory_id=memory_id, source="perplexity", account_id=account_id,
            project_path=None, project_key=None, file_name=Path(current.locator.split("#", 1)[0]).name,
            name=current.name, description=None, kind="saved_memory", content=current.content,
            content_size=len(current.content.encode("utf-8")),
            created_at=min(item.captured_at for item in items), updated_at=selected.effective_updated_at,
            relative_path=current.locator, current_version_id=selected.version_id,
            first_seen_at=min(item.captured_at for item in items),
            last_seen_at=max(item.captured_at for item in items),
            is_preserved_missing=latest_ids is not None and native_id not in latest_ids,
        ))
    return AgentMemoryParseResult(memories, sorted(versions, key=lambda item: item.version_id),
                                  [evidence[key] for key in sorted(evidence)])


@dataclass
class _ProjectInstructionObservation:
    content: str
    locator: str
    captured_at: pd.Timestamp | None
    project: dict
    legacy: bool = False


def _valid_space_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


def _project_capture_time(value: object) -> pd.Timestamp:
    if not isinstance(value, str) or not value:
        raise ValueError("Perplexity Project snapshot has no capture time")
    try:
        result = pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Perplexity Project snapshot has an invalid capture time") from None
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("Perplexity Project snapshot capture time must be timezone-aware")
    return result.tz_convert("UTC")


def _project_snapshot(raw_root: Path, space_dir: Path, manifest_path: Path) -> _ProjectInstructionObservation | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("complete") is False:
        return None
    if manifest.get("complete") is not True:
        raise ValueError("Perplexity Project snapshot has no completeness attestation")
    if (manifest.get("version"), manifest.get("source"), manifest.get("surface"),
            manifest.get("space_uuid")) != (1, "perplexity", "project_settings", space_dir.name):
        raise ValueError("Perplexity Project snapshot provenance mismatch")
    captured_at = _project_capture_time(manifest.get("captured_at"))
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {"project_settings.json"}:
        raise ValueError("Perplexity Project snapshot file manifest is incomplete")
    details_path = manifest_path.parent / "project_settings.json"
    content_bytes = details_path.read_bytes()
    file_info = files["project_settings.json"]
    if not isinstance(file_info, dict):
        raise ValueError("Perplexity Project snapshot file metadata is malformed")
    expected = file_info.get("sha256")
    if not isinstance(expected, str) or _digest(content_bytes) != expected:
        raise ValueError("Perplexity Project snapshot hash mismatch")
    project = json.loads(content_bytes)
    if not isinstance(project, dict) or project.get("uuid") != space_dir.name:
        raise ValueError("Perplexity Project snapshot identity mismatch")
    instructions = project.get("instructions")
    settings_complete = manifest.get("settings_complete")
    if (not isinstance(settings_complete, bool)
            or settings_complete != isinstance(instructions, str)):
        raise ValueError("Perplexity Project snapshot settings attestation mismatch")
    if not isinstance(instructions, str):
        return None
    locator = (details_path.relative_to(raw_root).as_posix() + "#/instructions")
    return _ProjectInstructionObservation(instructions, locator, captured_at, project)


def _legacy_project_observation(raw_root: Path, space_dir: Path) -> _ProjectInstructionObservation | None:
    """Read old current metadata only before append-only snapshots exist."""
    path = space_dir / "metadata.json"
    if not path.is_file():
        return None
    project = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(project, dict) or project.get("uuid") != space_dir.name:
        raise ValueError("Legacy Perplexity Project metadata identity mismatch")
    instructions = project.get("instructions")
    if not isinstance(instructions, str):
        return None
    locator = path.relative_to(raw_root).as_posix() + "#/instructions"
    return _ProjectInstructionObservation(instructions, locator, None, project, legacy=True)


def parse_project_instructions(raw_root: Path, account_id: str | None) -> AgentMemoryParseResult:
    """Replay verified Project settings history as scoped instructions.

    Legacy metadata with no capture timestamp remains queryable with unknown
    dates. Once snapshots exist for a Space, only complete snapshots determine
    current presence or clearing.
    """
    raw_root = Path(raw_root)
    history_root = raw_root / "_project_settings"
    space_roots: dict[str, Path] = {}
    if history_root.is_dir():
        space_roots.update({path.name: path for path in history_root.iterdir()
                            if path.is_dir() and not path.name.startswith(".")
                            and _valid_space_uuid(path.name)})
    spaces_root = raw_root / "spaces"
    if spaces_root.is_dir():
        for path in spaces_root.iterdir():
            if path.is_dir() and _valid_space_uuid(path.name):
                space_roots.setdefault(path.name, path)
    if not space_roots:
        return AgentMemoryParseResult([], [], [])
    if account_id is None:
        raise ValueError("Account UUID is required to project Perplexity Project instructions")

    memories: list[AgentMemory] = []
    versions: list[AgentMemoryVersion] = []
    evidence: dict[str, AgentMemoryTemporalEvidence] = {}
    for space_uuid, base_dir in sorted(space_roots.items()):
        observations: list[_ProjectInstructionObservation] = []
        snapshot_paths = sorted((history_root / space_uuid).glob("*/capture.json"))
        snapshot_paths = [path for path in snapshot_paths if not path.parent.name.startswith(".")]
        if snapshot_paths:
            for manifest_path in snapshot_paths:
                item = _project_snapshot(raw_root, history_root / space_uuid, manifest_path)
                if item is not None:
                    observations.append(item)
        else:
            legacy = _legacy_project_observation(raw_root, base_dir)
            if legacy is not None:
                observations.append(legacy)
        if not observations:
            continue

        observations.sort(key=lambda item: (
            item.captured_at is not None,
            item.captured_at or pd.Timestamp.min.tz_localize("UTC"),
            item.locator,
        ))
        nonempty = [item for item in observations if item.content != ""]
        if not nonempty:
            continue

        memory_id = f"perplexity:{account_id}:project_instructions/{space_uuid}"
        grouped: dict[str, list[_ProjectInstructionObservation]] = {}
        for item in nonempty:
            grouped.setdefault(_digest(item.content), []).append(item)

        version_by_digest: dict[str, AgentMemoryVersion] = {}
        current_digest = _digest(nonempty[-1].content)
        for digest, items in sorted(grouped.items()):
            times = [item.captured_at for item in items if item.captured_at is not None]
            first_seen = min(times) if times else None
            last_seen = max(times) if times else None
            instruction = items[-1].content
            version_id = f"{memory_id}:{digest}"
            locator = items[0].locator
            version = AgentMemoryVersion(
                version_id=version_id, memory_id=memory_id, source="perplexity",
                account_id=account_id, relative_path=locator,
                content_sha256=digest, content=instruction,
                content_size=len(instruction.encode("utf-8")), source_modified_at=None,
                source_birth_at=None, first_seen_at=first_seen, last_seen_at=last_seen,
                captured_at=first_seen, effective_created_at=first_seen,
                effective_updated_at=last_seen,
                created_at_basis="first_observed" if first_seen is not None else None,
                updated_at_basis="last_observed" if last_seen is not None else None,
                created_at_confidence="high" if first_seen is not None else "unknown",
                updated_at_confidence="high" if last_seen is not None else "unknown",
            )
            versions.append(version)
            version_by_digest[digest] = version
            for item in items:
                if item.captured_at is None:
                    continue
                evidence_id = _digest(_json([version_id, item.captured_at.isoformat(), item.locator]))
                evidence[evidence_id] = AgentMemoryTemporalEvidence(
                    evidence_id=evidence_id, memory_id=memory_id, version_id=version_id,
                    source="perplexity", account_id=account_id, evidence_type="capture_observed",
                    timestamp=item.captured_at, confidence="high", locator=item.locator,
                    details_json=_json({"space_uuid": space_uuid, "instructions_present": True}),
                    is_inference=False,
                )

        latest = observations[-1]
        if latest.content == "":
            prior = version_by_digest[current_digest]
            if latest.captured_at is not None:
                evidence_id = _digest(_json([prior.version_id, latest.captured_at.isoformat(), latest.locator]))
                evidence[evidence_id] = AgentMemoryTemporalEvidence(
                    evidence_id=evidence_id, memory_id=memory_id, version_id=prior.version_id,
                    source="perplexity", account_id=account_id, evidence_type="capture_observed",
                    timestamp=latest.captured_at, confidence="high", locator=latest.locator,
                    details_json=_json({"space_uuid": space_uuid, "instructions_present": True,
                                        "instructions_nonempty": False}),
                    is_inference=False,
                )

        selected = version_by_digest[current_digest]
        nonempty_times = [item.captured_at for item in nonempty if item.captured_at is not None]
        memories.append(AgentMemory(
            memory_id=memory_id, source="perplexity", account_id=account_id,
            project_path=None, project_key=space_uuid,
            file_name="project_settings.json", name=None, description=None,
            kind="project_instructions", content=nonempty[-1].content,
            content_size=len(nonempty[-1].content.encode("utf-8")),
            created_at=selected.effective_created_at, updated_at=selected.effective_updated_at,
            relative_path=nonempty[-1].locator, current_version_id=selected.version_id,
            first_seen_at=min(nonempty_times) if nonempty_times else None,
            last_seen_at=max(nonempty_times) if nonempty_times else None,
            is_preserved_missing=latest.content == "",
        ))

    return AgentMemoryParseResult(memories, sorted(versions, key=lambda item: item.version_id),
                                  [evidence[key] for key in sorted(evidence)])
