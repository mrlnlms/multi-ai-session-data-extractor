"""Project verified account snapshots into versioned memory tables."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from src.parsing.agent_memory import AgentMemoryParseResult
from src.schema.models import AgentMemory, AgentMemoryTemporalEvidence, AgentMemoryVersion

SURFACES = {
    "saved_memories": ("chatgpt_memories.json", "saved_memory"),
    "summary": ("chatgpt_memory_summary.json", "memory_summary"),
    "instructions": ("chatgpt_instructions.json", "account_instructions"),
}


def _hash(content: str | bytes) -> str:
    return hashlib.sha256(content.encode("utf-8") if isinstance(content, str) else content).hexdigest()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _time(value) -> pd.Timestamp | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = pd.to_datetime(value, unit="s", utc=True) if isinstance(value, (int, float)) else pd.to_datetime(value, utc=True)
        return None if pd.isna(result) else result
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass
class Observation:
    key: str
    kind: str
    content: str
    locator: str
    native: dict
    captured_at: pd.Timestamp | None
    file_name: str


def _records(payload: dict, surface: str, locator: str, captured_at) -> list[Observation]:
    filename, kind = SURFACES[surface]
    if not isinstance(payload, dict):
        raise ValueError("Account memory payload must be an object")
    if surface != "saved_memories":
        if surface == "summary" and not isinstance(payload.get("sections"), list):
            raise ValueError("Summary payload has no sections list")
        return [Observation(surface, kind, _json(payload), locator, payload, captured_at, filename)]
    field = "memories" if payload.get("memories") is not None else "memory_entries"
    entries = payload.get(field)
    if not isinstance(entries, list):
        raise ValueError("Saved-memory payload has no entries list")
    records = []
    seen = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
            raise ValueError("Saved-memory entry has no native ID")
        if entry["id"] in seen or not isinstance(entry.get("content"), str):
            raise ValueError("Duplicate or malformed saved-memory entry")
        seen.add(entry["id"])
        records.append(Observation(
            f"saved_memories/{quote(entry['id'], safe='')}", kind, entry["content"],
            f"{locator}#/{field}/{index}", {k: v for k, v in entry.items() if k != "content"},
            captured_at, filename,
        ))
    return records


def _native_dates(observation: Observation):
    native = observation.native
    if observation.kind == "saved_memory":
        last_updated = native.get("last_updated")
        values = (
            ("native_created_timestamp", native.get("created_timestamp"), "high"),
            ("native_last_updated", last_updated.get("timestamp") if isinstance(last_updated, dict) else None, "high"),
            ("native_updated_at", native.get("updated_at"), "medium"),
        )
    elif observation.kind == "memory_summary":
        values = (("summary_generated_at", native.get("generatedAtIso"), "high"),)
    else:
        values = ()
    return [(key, parsed, confidence) for key, value, confidence in values if (parsed := _time(value)) is not None]


def parse_account_memory(raw_root: Path, account_id: str | None) -> AgentMemoryParseResult:
    """Replay dated captures; retain absent entries and reject damaged history.

    Current exports are a fallback only when that surface has no complete
    snapshot. Older structured exports join known native identities; otherwise
    they remain opaque, undated legacy documents.
    Checksum records remain capture metadata, not memory documents.
    """
    raw_root = Path(raw_root)
    history = raw_root / "_account_memory"
    if not history.exists() and not any((raw_root / name).is_file() for name, _ in SURFACES.values()) and not (raw_root / "chatgpt_memories.md").is_file():
        return AgentMemoryParseResult([], [], [])
    if account_id is None:
        raise ValueError("Account UUID is required to project ChatGPT memories")

    observations = []
    latest_saved_keys = None
    covered_hashes = set()
    for surface, (filename, _) in SURFACES.items():
        captures = []
        for metadata_path in sorted((history / surface).glob("*/capture.json")):
            if metadata_path.parent.name.startswith("."):
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("complete") is False:
                continue
            if metadata.get("version") != 1:
                raise ValueError("Unsupported account snapshot version")
            if metadata.get("source") != "chatgpt" or metadata.get("surface") != surface:
                raise ValueError("Account snapshot provenance mismatch")
            captured = _time(metadata.get("captured_at"))
            if captured is None:
                raise ValueError("Account snapshot lacks a valid capture timestamp")
            files = metadata.get("files", {})
            if filename not in files:
                raise ValueError("Account snapshot lacks its native payload")
            for name, info in files.items():
                if Path(name).name != name:
                    raise ValueError("Invalid snapshot file name")
                content = (metadata_path.parent / name).read_bytes()
                if _hash(content) != info.get("sha256"):
                    raise ValueError("Account snapshot hash mismatch")
                covered_hashes.add((name, _hash(content)))
            path = metadata_path.parent / filename
            records = _records(json.loads(path.read_bytes()), surface, path.relative_to(raw_root).as_posix(), captured)
            captures.append((captured, metadata_path.as_posix(), records))
        for _, _, records in sorted(captures):
            observations.extend(records)
            if surface == "saved_memories":
                latest_saved_keys = {item.key for item in records}
        if not captures and (path := raw_root / filename).is_file():
            content = path.read_bytes()
            observations.extend(_records(json.loads(content), surface, filename, None))
            covered_hashes.add((filename, _hash(content)))

    # Native IDs or an already-known account surface can establish identity
    # without a capture date. Markdown cannot be split into native entries.
    legacy_files = [(path.parent.name, path) for path in (history / "prior_exports").glob("*/*") if path.is_file()]
    markdown = raw_root / "chatgpt_memories.md"
    if markdown.is_file():
        legacy_files.append((markdown.name, markdown))
    legacy_seen = set()
    known_keys = {item.key for item in observations}
    surface_by_file = {name: surface for surface, (name, _) in SURFACES.items()}
    for name, path in sorted(legacy_files):
        if name not in {"chatgpt_memories.md", *(item[0] for item in SURFACES.values())}:
            continue
        content = path.read_bytes()
        digest = _hash(content)
        if (name, digest) in covered_hashes or (name, digest) in legacy_seen:
            continue
        legacy_seen.add((name, digest))
        if name in surface_by_file:
            try:
                records = _records(json.loads(content), surface_by_file[name], path.relative_to(raw_root).as_posix(), None)
            except (ValueError, TypeError):
                records = []
            if records and all(item.key in known_keys for item in records):
                observations.extend(records)
                continue
        observations.append(Observation(
            f"legacy_exports/{name}/{digest}", "legacy_export", content.decode("utf-8"),
            path.relative_to(raw_root).as_posix(), {}, None, name,
        ))

    memories, versions, evidence = [], [], {}
    by_key = {}
    for item in observations:
        by_key.setdefault(item.key, []).append(item)
    for key, items in sorted(by_key.items()):
        items.sort(key=lambda item: (item.captured_at or pd.Timestamp.min.tz_localize("UTC"), item.locator))
        memory_id = f"chatgpt:{account_id}:{key}"
        by_hash = {}
        for item in items:
            by_hash.setdefault(_hash(item.content), []).append(item)
        selected = None
        for digest, observed in sorted(by_hash.items()):
            version_id = f"{memory_id}:{digest}"
            timestamps = [item.captured_at for item in observed if item.captured_at is not None]
            first_seen = min(timestamps) if timestamps else None
            last_seen = max(timestamps) if timestamps else None
            chosen_dates = {
                name: (ts, confidence)
                for item in observed for name, ts, confidence in _native_dates(item)
            }
            creation_key = "native_created_timestamp" if observed[-1].kind == "saved_memory" else "summary_generated_at"
            created, created_confidence = chosen_dates.get(creation_key, (first_seen, "high" if first_seen is not None else "unknown"))
            created_basis = creation_key if creation_key in chosen_dates else ("first_observed" if first_seen is not None else None)
            update_key = next((name for name in ("native_last_updated", "native_updated_at", "summary_generated_at") if name in chosen_dates), None)
            modified, updated_confidence = chosen_dates.get(update_key, (None, "high" if last_seen is not None else "unknown"))
            version = AgentMemoryVersion(
                version_id=version_id, memory_id=memory_id, source="chatgpt", account_id=account_id,
                relative_path=observed[0].locator, content_sha256=digest,
                content=observed[0].content, content_size=len(observed[0].content.encode("utf-8")),
                source_modified_at=modified, source_birth_at=None, first_seen_at=first_seen,
                last_seen_at=last_seen, captured_at=first_seen,
                effective_created_at=created, effective_updated_at=modified if modified is not None else last_seen,
                created_at_basis=created_basis, updated_at_basis=update_key or ("last_observed" if last_seen is not None else None),
                created_at_confidence=created_confidence, updated_at_confidence=updated_confidence,
            )
            versions.append(version)
            if digest == _hash(items[-1].content):
                selected = version
            for item in observed:
                temporal = [("capture_observed" if item.captured_at is not None else "legacy_export", item.captured_at,
                             "high" if item.captured_at is not None else "unknown"), *_native_dates(item)]
                if item.captured_at is not None and item.captured_at == first_seen:
                    temporal.append(("first_observed", first_seen, "high"))
                if item.captured_at is not None and item.captured_at == last_seen:
                    temporal.append(("last_observed", last_seen, "high"))
                for kind, timestamp, confidence in temporal:
                    evidence_id = _hash(_json([version_id, kind, timestamp.isoformat() if timestamp is not None else None, item.locator]))
                    evidence[evidence_id] = AgentMemoryTemporalEvidence(
                        evidence_id=evidence_id, memory_id=memory_id, version_id=version_id,
                        source="chatgpt", account_id=account_id, evidence_type=kind,
                        timestamp=timestamp, confidence=confidence, locator=item.locator,
                        details_json=_json({"native_metadata": item.native}), is_inference=False,
                    )
        assert selected is not None
        seen = [item.captured_at for item in items if item.captured_at is not None]
        current = items[-1]
        memories.append(AgentMemory(
            memory_id=memory_id, source="chatgpt", account_id=account_id, project_path=None, project_key=None,
            file_name=current.file_name, name=None, description=None, kind=current.kind,
            content=current.content, content_size=len(current.content.encode("utf-8")),
            created_at=selected.effective_created_at, updated_at=selected.effective_updated_at,
            relative_path=current.locator, current_version_id=selected.version_id,
            first_seen_at=min(seen) if seen else None, last_seen_at=max(seen) if seen else None,
            is_preserved_missing=current.kind == "saved_memory" and latest_saved_keys is not None and key not in latest_saved_keys,
        ))
    return AgentMemoryParseResult(memories, sorted(versions, key=lambda item: item.version_id),
                                  [evidence[key] for key in sorted(evidence)])
