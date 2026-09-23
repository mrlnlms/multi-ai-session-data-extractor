"""Parser de memory files (Claude Code per-project, Codex global).

Le markdown com frontmatter YAML opcional, classifica por kind, retorna
lista de AgentMemory pronta pra parquet.
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from src.schema.models import (
    AgentMemory,
    AgentMemoryTemporalEvidence,
    AgentMemoryVersion,
    VALID_MEMORY_KINDS,
)

logger = logging.getLogger(__name__)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_FRONTMATTER_SCALAR_RE = re.compile(
    r"^\s*(type|name|description)\s*:\s*(\S.*?)\s*$",
    re.IGNORECASE,
)
_FILENAME_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-_](\d{2})[-_](\d{2})(?!\d)")
_EXPLICIT_DATE_RE = re.compile(
    r"(?im)^\s*(?:created(?:_at)?|creation date|date)\s*:\s*(20\d{2}-\d{2}-\d{2}(?:[T ][^\s]+)?)\s*$"
)


@dataclass
class AgentMemoryParseResult:
    memories: list[AgentMemory]
    versions: list[AgentMemoryVersion]
    temporal_evidence: list[AgentMemoryTemporalEvidence]


def _timestamp(value: object) -> Optional[pd.Timestamp]:
    if value is None or value == "":
        return None
    try:
        return pd.Timestamp(value)
    except (ValueError, TypeError):
        return None


def _evidence_id(version_id: str, evidence_type: str, timestamp: pd.Timestamp) -> str:
    payload = f"{version_id}\0{evidence_type}\0{timestamp.isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_evidence(
    *, memory_id: str, version_id: str, source: str, evidence_type: str,
    timestamp: pd.Timestamp, confidence: str, locator: str, is_inference: bool,
) -> AgentMemoryTemporalEvidence:
    return AgentMemoryTemporalEvidence(
        evidence_id=_evidence_id(version_id, evidence_type, timestamp),
        memory_id=memory_id, version_id=version_id, source=source,
        evidence_type=evidence_type, timestamp=timestamp, confidence=confidence,
        locator=locator, details_json=None, is_inference=is_inference,
    )


def _extract_frontmatter_scalars(fm_text: str) -> dict[str, str]:
    """Best-effort extraction for malformed YAML frontmatter.

    Agent memory files are often written as free text. A colon in an
    unquoted ``name`` or ``description`` makes otherwise useful frontmatter
    invalid YAML. On that specific failure path, retain only the three scalar
    fields the schema understands. Nested values and empty/ambiguous lines are
    deliberately ignored.
    """
    fields: dict[str, str] = {}
    for line in fm_text.splitlines():
        match = _FRONTMATTER_SCALAR_RE.match(line)
        if match:
            fields[match.group(1).lower()] = match.group(2)
    return fields


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Retorna (dict_frontmatter, body), com fallback seguro para YAML invalido."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    fm_text, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_text)
        if not isinstance(fm, dict):
            return {}, content
        return fm, body
    except yaml.YAMLError as e:
        fallback = _extract_frontmatter_scalars(fm_text)
        if fallback:
            logger.info(
                "frontmatter YAML invalid; salvaged scalar metadata fields: %s",
                ", ".join(sorted(fallback)),
            )
            return fallback, body
        logger.warning("frontmatter parse failed without recoverable metadata: %s", e)
        return {}, content


def _decode_kind(file_name: str, frontmatter: dict) -> str:
    if file_name == "MEMORY.md":
        return "index"
    t = frontmatter.get("type")
    if isinstance(t, str) and t in VALID_MEMORY_KINDS:
        return t
    return "other"


def parse_agent_memory_file(
    *,
    path: Path,
    source: str,
    project_path: Optional[str],
    project_key: Optional[str],
    is_preserved_missing: bool,
    timestamp_ns: Optional[int] = None,
    relative_path: Optional[str] = None,
) -> AgentMemory:
    """Le 1 arquivo .md, retorna AgentMemory."""
    content = path.read_text(encoding="utf-8")
    fm, _body = parse_frontmatter(content)
    kind = _decode_kind(path.name, fm)
    name = fm.get("name") if isinstance(fm.get("name"), str) else None
    description = fm.get("description") if isinstance(fm.get("description"), str) else None

    if timestamp_ns is None:
        mtime = pd.Timestamp.fromtimestamp(path.stat().st_mtime, tz="UTC")
    else:
        mtime = pd.Timestamp(timestamp_ns, unit="ns", tz="UTC")
    canonical_path = relative_path or (
        f"{project_key}/memory/{path.name}" if project_key else f"memories/{path.name}"
    )
    return AgentMemory(
        memory_id=f"{source}:{canonical_path}",
        source=source,
        project_path=project_path,
        project_key=project_key,
        file_name=path.name,
        name=name,
        description=description,
        kind=kind,
        content=content,
        content_size=len(content.encode("utf-8")),
        created_at=mtime,
        updated_at=mtime,
        relative_path=canonical_path,
        is_preserved_missing=is_preserved_missing,
    )


def _version_from_manifest(
    *, raw_root: Path, source: str, relative_path: str, version_data: dict,
) -> tuple[AgentMemoryVersion, list[AgentMemoryTemporalEvidence]]:
    digest = str(version_data["sha256"])
    memory_id = f"{source}:{relative_path}"
    version_id = f"{memory_id}:{digest}"
    version_path = raw_root / str(version_data.get("raw_path") or f"_memory_versions/{digest}.md")
    content = version_path.read_text(encoding="utf-8")
    fm, _ = parse_frontmatter(content)
    source_mtime = _timestamp(version_data.get("source_modified_at"))
    source_birth = _timestamp(version_data.get("source_birth_at"))
    first_seen = _timestamp(version_data.get("first_seen_at"))
    last_seen = _timestamp(version_data.get("last_seen_at"))
    captured = _timestamp(version_data.get("captured_at"))
    evidence: list[AgentMemoryTemporalEvidence] = []

    explicit_structured = next(
        (_timestamp(fm.get(key)) for key in ("created_at", "created", "date") if fm.get(key)),
        None,
    )
    if explicit_structured is not None:
        evidence.append(_make_evidence(
            memory_id=memory_id, version_id=version_id, source=source,
            evidence_type="explicit_structured_timestamp", timestamp=explicit_structured,
            confidence="high", locator=f"{relative_path}:frontmatter", is_inference=False,
        ))
    if first_seen is not None:
        evidence.append(_make_evidence(
            memory_id=memory_id, version_id=version_id, source=source,
            evidence_type="first_observed", timestamp=first_seen, confidence="high",
            locator="_memory_metadata.json", is_inference=False,
        ))
    if source_birth is not None:
        evidence.append(_make_evidence(
            memory_id=memory_id, version_id=version_id, source=source,
            evidence_type="source_birthtime", timestamp=source_birth, confidence="medium",
            locator=relative_path, is_inference=False,
        ))
    if source_mtime is not None:
        evidence.append(_make_evidence(
            memory_id=memory_id, version_id=version_id, source=source,
            evidence_type="source_mtime", timestamp=source_mtime, confidence="high",
            locator=relative_path, is_inference=False,
        ))
    filename_match = _FILENAME_DATE_RE.search(Path(relative_path).name)
    filename_date = (
        pd.Timestamp("-".join(filename_match.groups()), tz="UTC") if filename_match else None
    )
    if filename_date is not None:
        evidence.append(_make_evidence(
            memory_id=memory_id, version_id=version_id, source=source,
            evidence_type="filename_timestamp", timestamp=filename_date, confidence="low",
            locator=relative_path, is_inference=True,
        ))
    content_match = _EXPLICIT_DATE_RE.search(content)
    content_date = _timestamp(content_match.group(1)) if content_match else None
    if content_date is not None and explicit_structured is None:
        evidence.append(_make_evidence(
            memory_id=memory_id, version_id=version_id, source=source,
            evidence_type="explicit_content_timestamp", timestamp=content_date,
            confidence="low", locator=f"{relative_path}:explicit-date-line", is_inference=True,
        ))

    created_candidates = [
        (explicit_structured, "explicit_structured_timestamp", "high"),
        (first_seen, "first_observed", "high"),
        (source_birth, "source_birthtime", "medium"),
        (filename_date, "filename_timestamp", "low"),
        (content_date, "explicit_content_timestamp", "low"),
    ]
    effective_created, created_basis, created_confidence = next(
        ((value, basis, confidence) for value, basis, confidence in created_candidates if value is not None),
        (None, None, "unknown"),
    )
    effective_updated = source_mtime if source_mtime is not None else last_seen
    updated_basis = "source_mtime" if source_mtime is not None else ("last_observed" if last_seen is not None else None)
    updated_confidence = "high" if effective_updated is not None else "unknown"
    version = AgentMemoryVersion(
        version_id=version_id, memory_id=memory_id, source=source,
        relative_path=relative_path, content_sha256=digest, content=content,
        content_size=len(content.encode("utf-8")), source_modified_at=source_mtime,
        source_birth_at=source_birth, first_seen_at=first_seen, last_seen_at=last_seen,
        captured_at=captured, effective_created_at=effective_created,
        effective_updated_at=effective_updated, created_at_basis=created_basis,
        updated_at_basis=updated_basis, created_at_confidence=created_confidence,
        updated_at_confidence=updated_confidence,
    )
    return version, evidence


def decode_project_path(project_dir: Path) -> Optional[str]:
    """Resolve cwd real lendo primeiro jsonl com campo `cwd`.

    encoded-cwd substitui '/' por '-' mas e ambiguo quando dir tem '-' no nome
    (ex: -Users-x-Desktop-code-maker-v2 vs /Users/x/Desktop/code-maker-v2).
    Sessions Claude Code gravam o cwd real numa das primeiras linhas do jsonl.

    Retorna None se nao conseguir resolver (project_dir sem jsonl).
    """
    for jsonl in project_dir.glob("*.jsonl"):
        try:
            with jsonl.open() as f:
                for i, line in enumerate(f):
                    if i > 50:  # cap scan -- cwd geralmente nas primeiras linhas
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cwd = obj.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        return cwd
        except Exception as e:
            logger.warning(f"decode_project_path: {jsonl.name} read failed: {e}")
            continue
    return None


def parse_memories_for_source(
    raw_root: Path,
    source: str,
    home_files: set[str],
) -> list[AgentMemory]:
    """Le memory files de data/raw/<source>/ e retorna lista de AgentMemory.

    Args:
        raw_root: ex. data/raw/Claude Code/ ou data/raw/Codex/
        source: 'claude_code', 'codex' ou 'gemini_cli'
        home_files: relative paths dos arquivos de memory presentes no HOME
            (gerado por current_source_files()) -- usado pra detectar preserved_missing
    """
    if source not in ("claude_code", "codex", "gemini_cli"):
        raise ValueError(f"agent_memory parser nao suporta source={source}")

    if not raw_root.exists():
        return []

    from src.capture.cli.memory_metadata import load_memory_metadata

    items: list[AgentMemory] = []
    timestamps = load_memory_metadata(raw_root)

    if source == "claude_code":
        for project_dir in sorted(raw_root.iterdir()):
            if not project_dir.is_dir():
                continue
            mem_dir = project_dir / "memory"
            if not mem_dir.is_dir():
                continue
            project_path = decode_project_path(project_dir)
            project_key = project_dir.name
            for md in sorted(mem_dir.glob("*.md")):
                rel = f"{project_dir.name}/memory/{md.name}"
                preserved = rel not in home_files
                try:
                    items.append(parse_agent_memory_file(
                        path=md,
                        source=source,
                        project_path=project_path,
                        project_key=project_key,
                        is_preserved_missing=preserved,
                        timestamp_ns=timestamps.get(rel),
                    ))
                except Exception as e:
                    logger.warning(f"agent_memory: failed to parse {md}: {e}")
                    continue
    elif source == "codex":
        mem_dir = raw_root / "memories"
        if mem_dir.is_dir():
            for md in sorted(mem_dir.rglob("*.md")):
                rel = f"memories/{md.relative_to(mem_dir)}"
                preserved = rel not in home_files
                try:
                    items.append(parse_agent_memory_file(
                        path=md,
                        source=source,
                        project_path=None,
                        project_key=None,
                        is_preserved_missing=preserved,
                        timestamp_ns=timestamps.get(rel),
                    ))
                except Exception as e:
                    logger.warning(f"agent_memory: failed to parse {md}: {e}")
                    continue
    elif source == "gemini_cli":
        mem_dir = raw_root / "_agent_memory"
        if mem_dir.is_dir():
            for md in sorted(mem_dir.rglob("*.md")):
                rel = md.relative_to(raw_root).as_posix()
                parts = Path(rel).parts
                project_key = parts[2] if len(parts) > 3 and parts[1] in {"projects", "private"} else None
                try:
                    items.append(parse_agent_memory_file(
                        path=md, source=source, project_path=None,
                        project_key=project_key, is_preserved_missing=rel not in home_files,
                        timestamp_ns=timestamps.get(rel), relative_path=rel,
                    ))
                except Exception as e:
                    logger.warning(f"agent_memory: failed to parse {md}: {e}")
                    continue

    # A v2 manifest is authoritative for version history. Preserve the legacy
    # scanner above as the compatibility path for raw trees not migrated yet.
    from src.capture.cli.memory_metadata import load_memory_manifest

    manifest = load_memory_manifest(raw_root, source)
    if not any(document.get("versions") for document in manifest.documents.values()):
        return items
    return parse_memory_archive(raw_root, source, home_files).memories


def parse_memory_archive(
    raw_root: Path,
    source: str,
    home_files: set[str],
) -> AgentMemoryParseResult:
    """Parse logical documents, immutable versions and temporal evidence."""
    if source not in ("claude_code", "codex", "gemini_cli"):
        raise ValueError(f"agent_memory parser nao suporta source={source}")
    from src.capture.cli.memory_metadata import load_memory_manifest

    manifest = load_memory_manifest(raw_root, source)
    memories: list[AgentMemory] = []
    versions: list[AgentMemoryVersion] = []
    evidence: list[AgentMemoryTemporalEvidence] = []
    for relative_path, document in sorted(manifest.documents.items()):
        parsed_versions: list[AgentMemoryVersion] = []
        for version_data in document.get("versions", []):
            try:
                version, version_evidence = _version_from_manifest(
                    raw_root=raw_root, source=source, relative_path=relative_path,
                    version_data=version_data,
                )
            except (OSError, KeyError, UnicodeError, ValueError) as error:
                logger.warning("agent_memory: failed version %s: %s", relative_path, error)
                continue
            parsed_versions.append(version)
            versions.append(version)
            evidence.extend(version_evidence)
        if not parsed_versions:
            continue
        current = parsed_versions[-1]
        fm, _ = parse_frontmatter(current.content)
        file_name = Path(relative_path).name
        if source == "claude_code":
            project_key = relative_path.split("/", 1)[0]
        elif source == "gemini_cli":
            parts = Path(relative_path).parts
            project_key = parts[2] if len(parts) > 3 and parts[1] in {"projects", "private"} else None
        else:
            project_key = None
        project_dir = raw_root / project_key if project_key else None
        project_path = decode_project_path(project_dir) if project_dir else None
        name = fm.get("name") if isinstance(fm.get("name"), str) else None
        description = fm.get("description") if isinstance(fm.get("description"), str) else None
        memories.append(AgentMemory(
            memory_id=current.memory_id, source=source, project_path=project_path,
            project_key=project_key, file_name=file_name, name=name,
            description=description, kind=_decode_kind(file_name, fm),
            content=current.content, content_size=current.content_size,
            created_at=current.effective_created_at, updated_at=current.effective_updated_at,
            relative_path=relative_path, current_version_id=current.version_id,
            first_seen_at=_timestamp(document.get("first_seen_at")),
            last_seen_at=_timestamp(document.get("last_seen_at")),
            is_preserved_missing=(
                not bool(document.get("is_present"))
                if "is_present" in document else relative_path not in home_files
            ),
        ))
    return AgentMemoryParseResult(memories, versions, evidence)
