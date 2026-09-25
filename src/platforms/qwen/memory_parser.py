"""Replay complete Qwen native snapshots into versioned account memories."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from src.parsing.agent_memory import AgentMemoryParseResult
from src.platforms.qwen.extractor.account_memory import PAGE_SIZE, _memory_page
from src.schema.models import AgentMemory, AgentMemoryTemporalEvidence, AgentMemoryVersion


def _digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _time(value: object, *, native: bool = False) -> pd.Timestamp | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        timestamp = pd.to_datetime(value, unit="s", utc=True) if native else pd.to_datetime(value, utc=True)
        return None if pd.isna(timestamp) else timestamp
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass
class _Observation:
    key: str
    kind: str
    content: str
    locator: str
    captured_at: pd.Timestamp
    created_at: pd.Timestamp | None
    updated_at: pd.Timestamp | None
    native: dict


def _capture(raw_root: Path, manifest_path: Path, surface: str) -> tuple[pd.Timestamp, list[_Observation]] | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("version") != 1 or manifest.get("source") != "qwen"
            or manifest.get("surface") != surface or not isinstance(manifest.get("complete"), bool)):
        raise ValueError("Unsupported Qwen memory snapshot provenance")
    if not manifest["complete"]:
        return None
    captured = _time(manifest.get("captured_at"))
    if captured is None:
        raise ValueError("Qwen memory snapshot has no valid capture time")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Complete Qwen memory snapshot has no payload")
    for name, info in files.items():
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or not isinstance(info, dict)
                or _digest((manifest_path.parent / relative).read_bytes()) != info.get("sha256")):
            raise ValueError("Qwen memory snapshot hash or path mismatch")

    observations: list[_Observation] = []
    if surface == "saved_memories":
        names = sorted(files)
        seen: set[str] = set()
        expected_total = None
        for index, name in enumerate(names, 1):
            if name != f"pages/{index:04d}.json":
                raise ValueError("Qwen memory pages are not consecutive")
            wrapper = json.loads((manifest_path.parent / name).read_text(encoding="utf-8"))
            if wrapper.get("request") != {"page_size": PAGE_SIZE, "page_num": index}:
                raise ValueError("Qwen memory page request mismatch")
            nodes, total = _memory_page(wrapper.get("response"))
            if expected_total is None:
                expected_total = total
            if total != expected_total or len(nodes) > PAGE_SIZE:
                raise ValueError("Qwen memory page count changed")
            for node_index, node in enumerate(nodes):
                native_id = node["memory_node_id"]
                if native_id in seen:
                    raise ValueError("Duplicate Qwen memory ID")
                seen.add(native_id)
                locator = ((manifest_path.parent / name).relative_to(raw_root).as_posix()
                           + f"#/response/data/memory_nodes/{node_index}")
                observations.append(_Observation(
                    key=f"saved_memories/{quote(native_id, safe='')}", kind="saved_memory",
                    content=node["content"], locator=locator, captured_at=captured,
                    created_at=_time(node["created_at"], native=True),
                    updated_at=_time(node["updated_at"], native=True),
                    native={k: v for k, v in node.items() if k != "content"},
                ))
            if len(seen) < total and len(nodes) != PAGE_SIZE:
                raise ValueError("Incomplete Qwen memory page")
            if len(seen) == total and index != len(names):
                raise ValueError("Qwen memory has pages after total")
        if len(seen) != expected_total:
            raise ValueError("Incomplete Qwen memory snapshot")
    else:
        if set(files) != {"settings.json"}:
            raise ValueError("Unexpected Qwen personalization snapshot files")
        payload = json.loads((manifest_path.parent / "settings.json").read_text(encoding="utf-8"))
        data = payload.get("data") if isinstance(payload, dict) else None
        if (payload.get("success") is not True or not isinstance(data, dict)
                or not isinstance(data.get("memory"), dict)
                or ("personalization" in data and data["personalization"] is not None
                    and not isinstance(data["personalization"], dict))):
            raise ValueError("Malformed Qwen personalization response")
        personalization = data.get("personalization") or {}
        if any(isinstance(personalization.get(key), str) and personalization[key].strip()
               for key in ("name", "description", "instruction", "style")):
            observations.append(_Observation(
                key="personalization", kind="account_instructions",
                content=_json(personalization),
                locator=((manifest_path.parent / "settings.json").relative_to(raw_root).as_posix()
                         + "#/data/personalization"),
                captured_at=captured, created_at=None, updated_at=None,
                native={"enable_for_new_chat": personalization.get("enable_for_new_chat")},
            ))
    return captured, observations


def parse_account_memory(raw_root: Path, account_id: str | None) -> AgentMemoryParseResult:
    raw_root = Path(raw_root)
    history = raw_root / "_account_memory" / "native"
    if not history.exists():
        return AgentMemoryParseResult([], [], [])
    if account_id is None:
        raise ValueError("Account UUID is required to project Qwen memories")
    grouped: dict[str, list[_Observation]] = {}
    latest_ids: dict[str, set[str]] = {}
    for surface in ("saved_memories", "personalization"):
        captures = []
        for path in sorted((history / surface).glob("*/capture.json")):
            if path.parent.name.startswith("."):
                continue
            result = _capture(raw_root, path, surface)
            if result is not None:
                captures.append((result[0], path.as_posix(), result[1]))
        for _, _, items in sorted(captures):
            latest_ids[surface] = {item.key for item in items}
            for item in items:
                grouped.setdefault(item.key, []).append(item)

    memories: list[AgentMemory] = []
    versions: list[AgentMemoryVersion] = []
    evidence: dict[str, AgentMemoryTemporalEvidence] = {}
    for key, items in sorted(grouped.items()):
        items.sort(key=lambda item: (item.captured_at, item.locator))
        memory_id = f"qwen:{account_id}:{key}"
        by_hash: dict[str, list[_Observation]] = {}
        for item in items:
            by_hash.setdefault(_digest(item.content), []).append(item)
        current_version = None
        for content_hash, observed in sorted(by_hash.items()):
            version_id = f"{memory_id}:{content_hash}"
            first_seen = min(item.captured_at for item in observed)
            last_seen = max(item.captured_at for item in observed)
            births = [item.created_at for item in observed if item.created_at is not None]
            updates = [item.updated_at for item in observed if item.updated_at is not None]
            birth = min(births) if births else None
            updated = max(updates) if updates else None
            versions.append(AgentMemoryVersion(
                version_id=version_id, memory_id=memory_id, source="qwen", account_id=account_id,
                relative_path=observed[0].locator, content_sha256=content_hash,
                content=observed[0].content, content_size=len(observed[0].content.encode("utf-8")),
                source_modified_at=updated, source_birth_at=birth,
                first_seen_at=first_seen, last_seen_at=last_seen, captured_at=first_seen,
                effective_created_at=birth or first_seen, effective_updated_at=updated or last_seen,
                created_at_basis="native_created_at" if birth is not None else "first_observed",
                updated_at_basis="native_updated_at" if updated is not None else "last_observed",
                created_at_confidence="high", updated_at_confidence="high",
            ))
            if content_hash == _digest(items[-1].content):
                current_version = versions[-1]
            for item in observed:
                for evidence_type, timestamp in (
                    ("capture_observed", item.captured_at),
                    ("native_created_at", item.created_at),
                    ("native_updated_at", item.updated_at),
                ):
                    if timestamp is None:
                        continue
                    evidence_id = _digest(_json([version_id, evidence_type, timestamp.isoformat(), item.locator]))
                    evidence[evidence_id] = AgentMemoryTemporalEvidence(
                        evidence_id=evidence_id, memory_id=memory_id, version_id=version_id,
                        source="qwen", account_id=account_id, evidence_type=evidence_type,
                        timestamp=timestamp, confidence="high", locator=item.locator,
                        details_json=_json(item.native), is_inference=False,
                    )
        assert current_version is not None
        current = items[-1]
        first_seen = min(item.captured_at for item in items)
        last_seen = max(item.captured_at for item in items)
        surface = "saved_memories" if current.kind == "saved_memory" else "personalization"
        memories.append(AgentMemory(
            memory_id=memory_id, source="qwen", account_id=account_id,
            project_path=None, project_key=None,
            file_name=Path(current.locator.split("#", 1)[0]).name,
            name="Customize Qwen" if surface == "personalization" else None,
            description=None, kind=current.kind, content=current.content,
            content_size=len(current.content.encode("utf-8")),
            created_at=current.created_at or first_seen,
            updated_at=current_version.effective_updated_at,
            relative_path=current.locator, current_version_id=current_version.version_id,
            first_seen_at=first_seen, last_seen_at=last_seen,
            is_preserved_missing=(surface in latest_ids and key not in latest_ids[surface]),
        ))
    return AgentMemoryParseResult(
        memories, sorted(versions, key=lambda item: item.version_id),
        [evidence[key] for key in sorted(evidence)],
    )
