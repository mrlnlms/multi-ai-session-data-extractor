"""Audit and explicitly remove redundant raw/merged copies backed by the vault.

Dry-run is the default. ``--apply`` removes only paths whose bytes are checked
again against a content-addressed blob in ``data/assets`` immediately before
unlinking them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

from src.operations.asset_coverage_audit import (
    RepresentationEvidence,
    inventory_legacy_asset_files,
)


@dataclass(frozen=True)
class RetentionCandidate:
    path: str
    source: str
    layer: str
    size_bytes: int
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _layer(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    return parts[0] if parts and parts[0] in {"raw", "merged"} else None


def audit_retention(
    data_root: Path,
    evidence: Iterable[RepresentationEvidence] | None = None,
) -> dict[str, object]:
    """Classify legacy copies without changing archive contents."""
    data_root = Path(data_root)
    vault_root = data_root / "assets" / "blobs" / "sha256"
    rows = inventory_legacy_asset_files(data_root) if evidence is None else list(evidence)
    by_path = {
        item.evidence_path: item
        for item in rows
        if _layer(item.evidence_path) is not None
    }
    candidates: list[RetentionCandidate] = []
    blocked: list[dict[str, object]] = []
    inode_candidates: dict[tuple[int, int], list[tuple[os.stat_result, int]]] = {}

    for relative, item in sorted(by_path.items()):
        path = data_root / relative
        if path.is_symlink() or not path.is_file():
            blocked.append({"path": relative, "reason": "missing_or_non_regular"})
            continue
        stat = path.stat()
        digest = _sha256(path)
        blob = vault_root / digest[:2] / digest
        if not blob.is_file():
            blocked.append({"path": relative, "reason": "vault_blob_missing"})
            continue
        blob_stat = blob.stat()
        if blob_stat.st_size != stat.st_size or _sha256(blob) != digest:
            blocked.append({"path": relative, "reason": "vault_blob_mismatch"})
            continue
        candidate = RetentionCandidate(
            path=relative,
            source=item.source,
            layer=_layer(relative) or "",
            size_bytes=stat.st_size,
            sha256=digest,
        )
        candidates.append(candidate)
        inode_candidates.setdefault((stat.st_dev, stat.st_ino), []).append((stat, stat.st_size))

    by_layer: dict[str, dict[str, int]] = {}
    by_source: dict[str, dict[str, int]] = {}
    for row in candidates:
        for target, key in ((by_layer, row.layer), (by_source, row.source)):
            group = target.setdefault(key, {"file_count": 0, "logical_bytes": 0})
            group["file_count"] += 1
            group["logical_bytes"] += row.size_bytes

    exclusive_allocated = 0
    for inode_rows in inode_candidates.values():
        stat = inode_rows[0][0]
        if len(inode_rows) >= stat.st_nlink:
            exclusive_allocated += stat.st_blocks * 512

    return {
        "mode": "read_only",
        "data_root": str(data_root.resolve()),
        "candidate_file_count": len(candidates),
        "candidate_logical_bytes": sum(row.size_bytes for row in candidates),
        "estimated_exclusive_allocated_bytes": exclusive_allocated,
        "unique_candidate_digests": len({row.sha256 for row in candidates}),
        "blocked_file_count": len(blocked),
        "by_layer": by_layer,
        "by_source": by_source,
        "candidates": [asdict(row) for row in candidates],
        "blocked": blocked,
    }


def apply_retention(data_root: Path, report: dict[str, object]) -> dict[str, object]:
    """Remove freshly audited candidates, refusing changed or unsafe paths."""
    data_root = Path(data_root).resolve()
    vault_root = data_root / "assets" / "blobs" / "sha256"
    removed: list[str] = []
    blocked: list[dict[str, str]] = []

    for row in report["candidates"]:
        relative = str(row["path"])
        layer = _layer(relative)
        path = data_root / relative
        if layer is None:
            blocked.append({"path": relative, "reason": "outside_legacy_layers"})
            continue
        try:
            path.resolve().relative_to((data_root / layer).resolve())
        except ValueError:
            blocked.append({"path": relative, "reason": "unsafe_resolved_path"})
            continue
        if path.is_symlink() or not path.is_file():
            blocked.append({"path": relative, "reason": "missing_or_non_regular"})
            continue

        before = path.stat()
        digest = _sha256(path)
        if digest != row["sha256"] or before.st_size != row["size_bytes"]:
            blocked.append({"path": relative, "reason": "candidate_changed"})
            continue
        blob = vault_root / digest[:2] / digest
        if not blob.is_file() or blob.stat().st_size != before.st_size or _sha256(blob) != digest:
            blocked.append({"path": relative, "reason": "vault_blob_missing_or_mismatch"})
            continue
        after = path.stat()
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_after != identity_before:
            blocked.append({"path": relative, "reason": "candidate_changed_during_check"})
            continue
        path.unlink()
        removed.append(relative)

    removed_set = set(removed)
    return {
        "mode": "apply",
        "data_root": str(data_root),
        "audited_candidate_file_count": report["candidate_file_count"],
        "removed_file_count": len(removed),
        "removed_logical_bytes": sum(
            int(row["size_bytes"])
            for row in report["candidates"]
            if row["path"] in removed_set
        ),
        "blocked_file_count": len(blocked),
        "removed": removed,
        "blocked": blocked,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="remove byte-proven raw/merged copies after revalidating each one",
    )
    args = parser.parse_args(argv)
    report = audit_retention(args.data_root)
    if args.apply:
        if report["blocked_file_count"]:
            print("Refusing --apply because the fresh audit contains blocked files.")
            return 1
        report = apply_retention(args.data_root, report)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        summary = {key: value for key, value in report.items() if key != "candidates"}
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(encoded, end="")
    return 1 if report["blocked_file_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
