"""Project classic Claude memory from preserved, dated pre-extractor exports.

The export's date is a directory label, not an item creation/update timestamp.
Its source JSON remains immutable under ``data/external``; this adapter only
materializes queryable documents and date-precision provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from src.account_catalog import AccountCatalogRecord, load_account_catalog
from src.parsing.agent_memory import AgentMemoryParseResult
from src.schema.models import AgentMemory, AgentMemoryTemporalEvidence, AgentMemoryVersion


_DATED_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCATOR_PREFIX = "data/external/claude-ai-snapshots"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_list(path: Path) -> list:
    if not path.is_file():
        raise FileNotFoundError(f"Claude historical snapshot file unavailable: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("Claude historical snapshot must contain one object")
    return value


def _catalog_account(user: dict, records: tuple[AccountCatalogRecord, ...]) -> str:
    email = user.get("email_address")
    if not isinstance(email, str) or not email.strip():
        raise ValueError("Claude historical user lacks email identity")
    matches = [record for record in records
               if record.platform == "Claude.ai" and isinstance(record.email, str)
               and record.email.casefold() == email.casefold()]
    if len(matches) != 1:
        raise ValueError("Claude historical account identity is not unique in catalog")
    return matches[0].account_id


@dataclass(frozen=True)
class _Observation:
    account_id: str
    key: str
    project_key: str | None
    content: str
    locator: str
    snapshot_date: date


def _read_snapshot(directory: Path, records: tuple[AccountCatalogRecord, ...]) -> list[_Observation]:
    snapshot_date = date.fromisoformat(directory.name)
    [user] = _read_list(directory / "users.json")
    [memory] = _read_list(directory / "memories.json")
    if not isinstance(user.get("uuid"), str) or memory.get("account_uuid") != user["uuid"]:
        raise ValueError("Claude historical export identity mismatch")
    account_id = _catalog_account(user, records)
    account_content = memory.get("conversations_memory")
    projects = memory.get("project_memories")
    if not isinstance(account_content, str) or not isinstance(projects, dict):
        raise ValueError("Claude historical memory payload has unsupported shape")

    locator_base = f"{_LOCATOR_PREFIX}/{directory.name}/memories.json#/0"
    observations = [_Observation(
        account_id=account_id, key="classic/account_conversations",
        project_key=None, content=account_content,
        locator=f"{locator_base}/conversations_memory", snapshot_date=snapshot_date,
    )]
    for project_key, content in sorted(projects.items()):
        if not isinstance(project_key, str):
            raise ValueError("Claude historical Project scope must be a UUID")
        try:
            uuid.UUID(project_key)
        except ValueError as exc:
            raise ValueError("Claude historical Project scope must be a UUID") from exc
        if not isinstance(content, str):
            raise ValueError("Claude historical Project memory must be text")
        observations.append(_Observation(
            account_id=account_id, key=f"classic/project/{project_key}",
            project_key=project_key, content=content,
            locator=f"{locator_base}/project_memories/{project_key}",
            snapshot_date=snapshot_date,
        ))
    return observations


def parse_historical_memory(snapshot_root: Path, catalog_path: Path) -> AgentMemoryParseResult:
    """Read all dated classic exports; fail if expected history is unavailable.

    ``legacy_export`` plus ``project_key`` keeps classic Project strings
    queryable without claiming equivalence to Melange ``project_memory`` topics.
    The directory date appears only in temporal evidence, with day precision.
    """
    snapshot_root = Path(snapshot_root)
    directories = sorted(path for path in snapshot_root.iterdir()
                         if path.is_dir() and _DATED_DIR.fullmatch(path.name)) if snapshot_root.is_dir() else []
    if not directories:
        raise FileNotFoundError("Claude historical snapshots unavailable")
    records = load_account_catalog(Path(catalog_path)).records
    grouped: dict[tuple[str, str], list[_Observation]] = defaultdict(list)
    for directory in directories:
        for observation in _read_snapshot(directory, records):
            grouped[(observation.account_id, observation.key)].append(observation)

    memories: list[AgentMemory] = []
    versions: list[AgentMemoryVersion] = []
    evidence: list[AgentMemoryTemporalEvidence] = []
    for (account_id, key), observations in sorted(grouped.items()):
        observations.sort(key=lambda item: (item.snapshot_date, item.locator))
        memory_id = f"claude_ai:{account_id}:{quote(key, safe='')}"
        by_hash: dict[str, list[_Observation]] = defaultdict(list)
        for observation in observations:
            by_hash[_digest(observation.content)].append(observation)
        for content_hash, same_content in sorted(by_hash.items()):
            first = same_content[0]
            version_id = f"{memory_id}:{content_hash}"
            versions.append(AgentMemoryVersion(
                version_id=version_id, memory_id=memory_id, source="claude_ai",
                account_id=account_id, relative_path=first.locator,
                content_sha256=content_hash, content=first.content,
                content_size=len(first.content.encode("utf-8")),
                source_modified_at=None, source_birth_at=None,
                first_seen_at=None, last_seen_at=None, captured_at=None,
                effective_created_at=None, effective_updated_at=None,
                created_at_basis=None, updated_at_basis=None,
            ))
            for observed in same_content:
                timestamp = pd.Timestamp(observed.snapshot_date, tz="UTC")
                details = _json({
                    "date_precision": "day",
                    "representation": "classic_structured_export",
                    "snapshot_date": observed.snapshot_date.isoformat(),
                })
                evidence.append(AgentMemoryTemporalEvidence(
                    evidence_id=_digest(_json([version_id, observed.locator, details])),
                    memory_id=memory_id, version_id=version_id,
                    source="claude_ai", account_id=account_id,
                    evidence_type="snapshot_directory_date", timestamp=timestamp,
                    confidence="medium", locator=observed.locator,
                    details_json=details, is_inference=True,
                ))
        current = observations[-1]
        memories.append(AgentMemory(
            memory_id=memory_id, source="claude_ai", account_id=account_id,
            project_path=None, project_key=current.project_key,
            file_name="memories.json", name=None,
            description="Classic Project memory export" if current.project_key else "Classic account memory export",
            kind="legacy_export", content=current.content,
            content_size=len(current.content.encode("utf-8")),
            created_at=None, updated_at=None, relative_path=current.locator,
            current_version_id=f"{memory_id}:{_digest(current.content)}",
            first_seen_at=None, last_seen_at=None, is_preserved_missing=False,
        ))
    return AgentMemoryParseResult(
        memories, sorted(versions, key=lambda item: item.version_id),
        sorted(evidence, key=lambda item: item.evidence_id),
    )
