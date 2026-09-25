"""Project preserved Gemini Instructions into versioned account records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from src.parsing.agent_memory import AgentMemoryParseResult
from src.platforms.gemini.extractor.api_client import validate_instructions_envelope
from src.schema.models import AgentMemory, AgentMemoryTemporalEvidence, AgentMemoryVersion


def _hash(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _time(value: object) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        raise ValueError("Invalid Gemini Instructions observation timestamp")
    return timestamp


def _native_time(pair: list[int]) -> pd.Timestamp:
    seconds, nanos = pair
    if seconds < 0 or not 0 <= nanos < 1_000_000_000:
        raise ValueError("Invalid Gemini Instructions native timestamp")
    return pd.to_datetime(seconds, unit="s", utc=True) + pd.Timedelta(nanoseconds=nanos)


@dataclass(frozen=True)
class _Observation:
    native_id: str
    content: str
    captured_at: pd.Timestamp
    locator: str
    native: list


def parse_account_instructions(raw_root: Path, account_id: str | None) -> AgentMemoryParseResult:
    """Replay verified native snapshots; only a valid full list can prove absence."""
    raw_root = Path(raw_root)
    history = raw_root / "instructions" / "observations.jsonl"
    if not history.exists():
        return AgentMemoryParseResult([], [], [])
    if account_id is None:
        raise ValueError("Account UUID is required for Gemini Instructions")

    captures: list[tuple[pd.Timestamp, int, list[_Observation]]] = []
    for line_number, line in enumerate(history.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        observation = json.loads(line)
        if not isinstance(observation, dict):
            raise ValueError("Malformed Gemini Instructions observation")
        observed_at = _time(observation.get("observed_at"))
        digest = observation.get("sha256")
        expected_path = f"instructions/snapshots/{digest}.json"
        if (not isinstance(digest, str) or len(digest) != 64
                or observation.get("snapshot_path") != expected_path):
            raise ValueError("Invalid Gemini Instructions snapshot reference")
        snapshot = raw_root / expected_path
        payload = snapshot.read_bytes()
        if _hash(payload) != digest:
            raise ValueError("Gemini Instructions snapshot hash mismatch")
        items = validate_instructions_envelope(json.loads(payload))
        captures.append((observed_at, line_number, [
            _Observation(
                native_id=item[0], content=item[1], captured_at=observed_at,
                locator=f"{expected_path}#/0/{index}", native=item,
            ) for index, item in enumerate(items)
        ]))

    if not captures:
        return AgentMemoryParseResult([], [], [])
    captures.sort(key=lambda entry: (entry[0], entry[1]))
    latest_ids = {item.native_id for item in captures[-1][2]}
    grouped: dict[str, list[_Observation]] = {}
    for _, _, items in captures:
        for item in items:
            grouped.setdefault(item.native_id, []).append(item)

    memories: list[AgentMemory] = []
    versions: list[AgentMemoryVersion] = []
    evidence: list[AgentMemoryTemporalEvidence] = []
    for native_id, observations in sorted(grouped.items()):
        key = quote(native_id, safe="")
        memory_id = f"gemini:{account_id}:instructions/{key}"
        versions_by_hash: dict[str, list[_Observation]] = {}
        for item in observations:
            versions_by_hash.setdefault(_hash(item.content), []).append(item)

        for content_hash, same_content in sorted(versions_by_hash.items()):
            first, last = same_content[0], same_content[-1]
            version_id = f"{memory_id}:{content_hash}"
            versions.append(AgentMemoryVersion(
                version_id=version_id, memory_id=memory_id, source="gemini",
                account_id=account_id, relative_path=first.locator,
                content_sha256=content_hash, content=first.content,
                content_size=len(first.content.encode("utf-8")),
                source_modified_at=None, source_birth_at=None,
                first_seen_at=first.captured_at, last_seen_at=last.captured_at,
                captured_at=first.captured_at,
                effective_created_at=first.captured_at,
                effective_updated_at=last.captured_at,
                created_at_basis="first_observed", updated_at_basis="last_observed",
                created_at_confidence="high", updated_at_confidence="high",
            ))
            for item in same_content:
                for evidence_type, timestamp in (
                    ("capture_observed", item.captured_at),
                    ("native_timestamp_field_2", _native_time(item.native[2])),
                    ("native_timestamp_field_4", _native_time(item.native[4])),
                ):
                    evidence_id = _hash(_json([
                        version_id, evidence_type, timestamp.isoformat(), item.locator,
                    ]))
                    evidence.append(AgentMemoryTemporalEvidence(
                        evidence_id=evidence_id, memory_id=memory_id,
                        version_id=version_id, source="gemini", account_id=account_id,
                        evidence_type=evidence_type, timestamp=timestamp,
                        confidence="high", locator=item.locator,
                        details_json=_json({"native": item.native[:1] + item.native[2:]}),
                        is_inference=False,
                    ))

        current = observations[-1]
        current_version_id = f"{memory_id}:{_hash(current.content)}"
        memories.append(AgentMemory(
            memory_id=memory_id, source="gemini", account_id=account_id,
            project_path=None, project_key=None,
            file_name="instructions", name="Instructions for Gemini",
            description=None, kind="account_instructions",
            content=current.content, content_size=len(current.content.encode("utf-8")),
            created_at=observations[0].captured_at,
            updated_at=current.captured_at,
            relative_path=current.locator, current_version_id=current_version_id,
            first_seen_at=observations[0].captured_at,
            last_seen_at=current.captured_at,
            is_preserved_missing=native_id not in latest_ids,
        ))
    unique_evidence = {item.evidence_id: item for item in evidence}
    return AgentMemoryParseResult(
        memories, sorted(versions, key=lambda item: item.version_id),
        [unique_evidence[key] for key in sorted(unique_evidence)],
    )
