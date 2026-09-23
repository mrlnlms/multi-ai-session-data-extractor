"""Preview or seed immutable history for already-preserved CLI memories."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from src.capture.cli.memory_metadata import (
    MANIFEST_NAME,
    MANIFEST_VERSION,
    VERSIONS_DIR,
    load_memory_manifest,
)


def _iso_ns(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preserved_files(raw_root: Path, source: str) -> dict[str, Path]:
    if source == "claude_code":
        paths = raw_root.glob("*/memory/*.md")
    elif source == "codex":
        paths = (raw_root / "memories").glob("**/*.md")
    elif source == "gemini_cli":
        paths = (raw_root / "_agent_memory").glob("**/*.md")
    else:
        raise ValueError(f"unsupported source: {source}")
    return {path.relative_to(raw_root).as_posix(): path for path in paths if path.is_file()}


def _legacy_mtimes(raw_root: Path) -> dict[str, int]:
    path = raw_root / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("version") != 1 or not isinstance(payload.get("files"), dict):
        return {}
    return {key: value for key, value in payload["files"].items() if isinstance(key, str) and isinstance(value, int)}


def reconstruct(
    *, raw_root: Path, source: str, source_root: Path | None = None, apply: bool = False,
) -> dict[str, Any]:
    """Return deterministic findings and optionally write the v2 seed."""
    raw_root = Path(raw_root)
    legacy_mtimes = _legacy_mtimes(raw_root)
    manifest = load_memory_manifest(raw_root, source)
    documents = json.loads(json.dumps(manifest.documents))
    findings: list[dict[str, Any]] = []
    source_observable = source_root is not None and Path(source_root).exists()

    for relative_path, preserved_path in sorted(_preserved_files(raw_root, source).items()):
        digest = _hash(preserved_path)
        document = documents.setdefault(relative_path, {
            "first_seen_at": None, "last_seen_at": None, "versions": [],
        })
        versions = document.setdefault("versions", [])
        existing = next((item for item in versions if item.get("sha256") == digest), None)
        live_path = Path(source_root) / relative_path if source_observable else None
        live_present = bool(live_path and live_path.is_file())
        if source_observable:
            document["is_present"] = live_present
        document.pop("legacy_mtime_ns", None)

        stat = live_path.stat() if live_present and live_path is not None else None
        source_mtime = _iso_ns(stat.st_mtime_ns) if stat else _iso_ns(legacy_mtimes.get(relative_path))
        birth_ns = getattr(stat, "st_birthtime_ns", None) if stat else None
        if stat and birth_ns is None and hasattr(stat, "st_birthtime"):
            birth_ns = int(stat.st_birthtime * 1_000_000_000)
        source_birth = _iso_ns(birth_ns)
        status = "already_versioned" if existing else "seed_version"
        findings.append({
            "relative_path": relative_path, "sha256": digest, "status": status,
            "source_modified_at": source_mtime, "source_birth_at": source_birth,
            "source_present": live_present if source_observable else None,
        })
        if existing is None:
            versions.append({
                "sha256": digest, "raw_path": f"{VERSIONS_DIR}/{digest}.md",
                "source_modified_at": source_mtime, "source_birth_at": source_birth,
                "first_seen_at": None, "last_seen_at": None, "captured_at": None,
            })

    output = {
        "source": source, "apply": apply, "documents": len(documents),
        "versions_to_seed": sum(item["status"] == "seed_version" for item in findings),
        "findings": findings,
    }
    if not apply:
        return output

    versions_dir = raw_root / VERSIONS_DIR
    versions_dir.mkdir(parents=True, exist_ok=True)
    files = _preserved_files(raw_root, source)
    for finding in findings:
        target = versions_dir / f"{finding['sha256']}.md"
        if target.exists():
            if _hash(target) != finding["sha256"]:
                raise ValueError(f"immutable memory version hash mismatch: {target}")
            continue
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        shutil.copyfile(files[finding["relative_path"]], temporary)
        if _hash(temporary) != finding["sha256"]:
            temporary.unlink(missing_ok=True)
            raise ValueError("preserved memory changed during reconstruction")
        os.replace(temporary, target)

    payload = {"version": MANIFEST_VERSION, "source": source, "documents": dict(sorted(documents.items()))}
    path = raw_root / MANIFEST_NAME
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", choices=("claude_code", "codex", "gemini_cli"), required=True
    )
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(reconstruct(
        raw_root=args.raw_root, source=args.source,
        source_root=args.source_root, apply=args.apply,
    ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
