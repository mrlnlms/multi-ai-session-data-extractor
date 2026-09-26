"""Project only explicit instructions from verified ChatGPT Project detail history."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from src.parsing.agent_memory import AgentMemoryParseResult
from src.platforms.chatgpt.extractor.project_settings import DETAIL_FILE, HISTORY_DIR, PROJECT_ID, _validate_detail
from src.schema.models import AgentMemory, AgentMemoryTemporalEvidence, AgentMemoryVersion


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_project_instructions(raw_root: Path, account_id: str | None) -> AgentMemoryParseResult:
    """Replay complete per-Project observations; never infer absent Projects."""
    raw_root = Path(raw_root)
    root = raw_root / HISTORY_DIR
    if not root.is_dir():
        return AgentMemoryParseResult([], [], [])
    if account_id is None:
        raise ValueError("Account UUID is required to project ChatGPT Project instructions")
    memories, versions, evidence = [], [], []
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir() or not PROJECT_ID.fullmatch(project_dir.name):
            continue
        observations = []
        for meta_path in sorted(project_dir.glob("*/capture.json")):
            if meta_path.parent.name.startswith("."):
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("complete") is False:
                continue
            if (meta.get("version"), meta.get("source"), meta.get("surface"), meta.get("project_id")) != (
                1, "chatgpt", "project_detail", project_dir.name
            ):
                raise ValueError("Project snapshot provenance mismatch")
            try:
                captured = pd.Timestamp(meta["captured_at"])
                if pd.isna(captured) or captured.tzinfo is None:
                    raise ValueError
                captured = captured.tz_convert("UTC")
                expected = meta["files"][DETAIL_FILE]["sha256"]
            except (KeyError, TypeError, ValueError):
                raise ValueError("Project snapshot metadata is incomplete") from None
            detail_path = meta_path.parent / DETAIL_FILE
            content = detail_path.read_bytes()
            if _sha(content) != expected:
                raise ValueError("Project snapshot hash mismatch")
            payload = json.loads(content)
            _validate_detail(project_dir.name, payload)
            gizmo = payload["gizmo"]
            locator = f"{detail_path.relative_to(raw_root).as_posix()}#/gizmo/instructions"
            observations.append((captured, locator, gizmo))
        if not observations:
            continue
        observations.sort(key=lambda item: (item[0], item[1]))
        instruction_observations = [item for item in observations
                                    if isinstance(item[2].get("instructions"), str)]
        nonempty = [item for item in instruction_observations if item[2]["instructions"]]
        if not nonempty:
            continue
        memory_id = f"chatgpt:{account_id}:project_instructions/{project_dir.name}"
        by_hash = {}
        for item in nonempty:
            digest = _sha(item[2]["instructions"].encode("utf-8"))
            by_hash.setdefault(digest, []).append(item)
        chosen_version = None
        for digest, items in sorted(by_hash.items()):
            first, last = items[0][0], items[-1][0]
            instruction = items[0][2]["instructions"]
            version_id = f"{memory_id}:{digest}"
            version = AgentMemoryVersion(
                version_id=version_id, memory_id=memory_id, source="chatgpt", account_id=account_id,
                relative_path=items[0][1], content_sha256=digest, content=instruction,
                content_size=len(instruction.encode("utf-8")), source_modified_at=None,
                source_birth_at=None, first_seen_at=first, last_seen_at=last, captured_at=first,
                effective_created_at=first, effective_updated_at=last,
                created_at_basis="first_observed", updated_at_basis="last_observed",
                created_at_confidence="high", updated_at_confidence="high",
            )
            versions.append(version)
            if digest == _sha(nonempty[-1][2]["instructions"].encode("utf-8")):
                chosen_version = version
            for captured, locator, gizmo in items:
                evidence_id = _sha(json.dumps([version_id, captured.isoformat(), locator]).encode("utf-8"))
                evidence.append(AgentMemoryTemporalEvidence(
                    evidence_id=evidence_id, memory_id=memory_id, version_id=version_id,
                    source="chatgpt", account_id=account_id, evidence_type="capture_observed",
                    timestamp=captured, confidence="high", locator=locator,
                    details_json=json.dumps({"memory_scope": gizmo.get("memory_scope"),
                                             "memory_enabled": gizmo.get("memory_enabled")}, sort_keys=True),
                    is_inference=False,
                ))
        latest = nonempty[-1]
        instruction = latest[2]["instructions"]
        assert chosen_version is not None
        memories.append(AgentMemory(
            memory_id=memory_id, source="chatgpt", account_id=account_id,
            project_path=None, project_key=project_dir.name,
            file_name=DETAIL_FILE, name=None, description=None, kind="project_instructions",
            content=instruction, content_size=len(instruction.encode("utf-8")),
            created_at=chosen_version.effective_created_at,
            updated_at=chosen_version.effective_updated_at,
            relative_path=latest[1], current_version_id=chosen_version.version_id,
            first_seen_at=nonempty[0][0], last_seen_at=latest[0],
            is_preserved_missing=observations[-1][2].get("instructions") == "",
        ))
    return AgentMemoryParseResult(memories, versions, evidence)
