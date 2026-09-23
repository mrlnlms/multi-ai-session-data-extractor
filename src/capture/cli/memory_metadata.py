"""Append-only observation manifests for CLI agent-memory files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any


MANIFEST_NAME = "_memory_metadata.json"
MANIFEST_VERSION = 2
VERSIONS_DIR = "_memory_versions"


@dataclass(frozen=True)
class MemoryObservationManifest:
    source: str
    documents: dict[str, dict[str, Any]]
    version: int = MANIFEST_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source": self.source,
            "documents": dict(sorted(self.documents.items())),
        }


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ns_iso(value: int | None) -> str | None:
    if value is None:
        return None
    return _iso_utc(datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc))


def _read_payload(raw_root: Path) -> dict[str, Any]:
    path = Path(raw_root) / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_memory_manifest(raw_root: Path, source: str | None = None) -> MemoryObservationManifest:
    """Load v2 state, or expose v1 paths as unversioned legacy documents."""
    payload = _read_payload(Path(raw_root))
    if payload.get("version") == MANIFEST_VERSION and isinstance(payload.get("documents"), dict):
        documents = {
            path: value for path, value in payload["documents"].items()
            if isinstance(path, str) and isinstance(value, dict)
        }
        return MemoryObservationManifest(
            source=str(payload.get("source") or source or ""),
            documents=documents,
        )

    documents: dict[str, dict[str, Any]] = {}
    if payload.get("version") == 1 and isinstance(payload.get("files"), dict):
        for relative_path, mtime_ns in payload["files"].items():
            if not isinstance(relative_path, str) or not isinstance(mtime_ns, int):
                continue
            documents[relative_path] = {
                "first_seen_at": None, "last_seen_at": None,
                "is_present": False, "legacy_mtime_ns": mtime_ns, "versions": [],
            }
    return MemoryObservationManifest(source=source or "", documents=documents)


def load_memory_metadata(raw_root: Path) -> dict[str, int]:
    """Compatibility projection mapping paths to the latest observed mtime."""
    manifest = load_memory_manifest(raw_root)
    result: dict[str, int] = {}
    for relative_path, document in manifest.documents.items():
        legacy = document.get("legacy_mtime_ns")
        if isinstance(legacy, int):
            result[relative_path] = legacy
            continue
        versions = document.get("versions")
        if not isinstance(versions, list) or not versions:
            continue
        timestamp = versions[-1].get("source_modified_at")
        if isinstance(timestamp, str):
            result[relative_path] = int(
                datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
                * 1_000_000_000
            )
    return result


def _source_memory_files(source_root: Path, source: str) -> dict[str, Path]:
    if source == "claude_code":
        return {path.relative_to(source_root).as_posix(): path for path in source_root.glob("*/memory/*.md")}
    if source == "codex":
        return {path.relative_to(source_root).as_posix(): path for path in (source_root / "memories").glob("**/*.md")}
    if source == "gemini_cli":
        return {
            path.relative_to(source_root).as_posix(): path
            for path in (source_root / "_agent_memory").glob("**/*.md")
        }
    raise ValueError(f"memory metadata does not support source={source}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_immutable_version(source_path: Path, target: Path, expected_sha256: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if _sha256(target) != expected_sha256:
            raise ValueError(f"immutable memory version hash mismatch: {target}")
        return
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    shutil.copyfile(source_path, temporary)
    if _sha256(temporary) != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"memory changed while being observed: {source_path}")
    os.replace(temporary, target)


def observe_memory_files(
    raw_root: Path,
    source_root: Path,
    source: str,
    captured_at: datetime | None = None,
    observed_files: dict[str, Path] | None = None,
) -> MemoryObservationManifest:
    """Observe live memories and atomically retain every distinct content hash."""
    raw_root = Path(raw_root)
    observed_at = _iso_utc(captured_at or datetime.now(timezone.utc))
    prior = load_memory_manifest(raw_root, source)
    documents = json.loads(json.dumps(prior.documents))
    current = observed_files if observed_files is not None else _source_memory_files(
        Path(source_root), source
    )
    for document in documents.values():
        document["is_present"] = False

    for relative_path, source_path in sorted(current.items()):
        stat = source_path.stat()
        digest = _sha256(source_path)
        _write_immutable_version(source_path, raw_root / VERSIONS_DIR / f"{digest}.md", digest)
        document = documents.setdefault(relative_path, {
            "first_seen_at": observed_at, "last_seen_at": observed_at,
            "is_present": True, "versions": [],
        })
        if document.get("first_seen_at") is None:
            document["first_seen_at"] = observed_at
        document["last_seen_at"] = observed_at
        document["is_present"] = True
        document.pop("legacy_mtime_ns", None)
        versions = document.setdefault("versions", [])
        matching = next((item for item in versions if item.get("sha256") == digest), None)
        birth_ns = getattr(stat, "st_birthtime_ns", None)
        if birth_ns is None and hasattr(stat, "st_birthtime"):
            birth_ns = int(stat.st_birthtime * 1_000_000_000)
        if matching is None:
            versions.append({
                "sha256": digest, "raw_path": f"{VERSIONS_DIR}/{digest}.md",
                "source_modified_at": _ns_iso(stat.st_mtime_ns),
                "source_birth_at": _ns_iso(birth_ns),
                "first_seen_at": observed_at, "last_seen_at": observed_at,
                "captured_at": observed_at,
            })
        else:
            if matching.get("first_seen_at") is None:
                matching["first_seen_at"] = observed_at
            if matching.get("captured_at") is None:
                matching["captured_at"] = observed_at
            matching["last_seen_at"] = observed_at

    manifest = MemoryObservationManifest(source=source, documents=documents)
    raw_root.mkdir(parents=True, exist_ok=True)
    path = raw_root / MANIFEST_NAME
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return manifest


def update_memory_metadata(raw_root: Path, source_root: Path, source: str) -> dict[str, int]:
    """Backward-compatible entrypoint; observation now also preserves versions."""
    observe_memory_files(raw_root, source_root, source)
    return load_memory_metadata(raw_root)
