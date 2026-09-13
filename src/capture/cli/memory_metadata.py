"""Reproducible source metadata for CLI agent-memory files."""

from __future__ import annotations

import json
from pathlib import Path


MANIFEST_NAME = "_memory_metadata.json"
MANIFEST_VERSION = 1


def load_memory_metadata(raw_root: Path) -> dict[str, int]:
    """Load relative memory paths mapped to source mtime nanoseconds."""
    path = Path(raw_root) / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("version") != MANIFEST_VERSION or not isinstance(payload.get("files"), dict):
        return {}
    return {
        relative_path: mtime_ns
        for relative_path, mtime_ns in payload["files"].items()
        if isinstance(relative_path, str) and isinstance(mtime_ns, int)
    }


def _source_memory_files(source_root: Path, source: str) -> dict[str, Path]:
    if source == "claude_code":
        return {
            str(path.relative_to(source_root)): path
            for path in source_root.glob("*/memory/*.md")
        }
    if source == "codex":
        return {
            str(path.relative_to(source_root)): path
            for path in (source_root / "memories").glob("**/*.md")
        }
    raise ValueError(f"memory metadata does not support source={source}")


def update_memory_metadata(raw_root: Path, source_root: Path, source: str) -> dict[str, int]:
    """Update current mtimes while retaining metadata for preserved-missing files."""
    raw_root = Path(raw_root)
    metadata = load_memory_metadata(raw_root)
    for relative_path, source_path in _source_memory_files(Path(source_root), source).items():
        metadata[relative_path] = source_path.stat().st_mtime_ns

    raw_root.mkdir(parents=True, exist_ok=True)
    manifest = raw_root / MANIFEST_NAME
    temporary = manifest.with_suffix(".tmp")
    payload = {"version": MANIFEST_VERSION, "files": dict(sorted(metadata.items()))}
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(manifest)
    return metadata
