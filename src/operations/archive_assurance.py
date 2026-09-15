"""Persist and reuse a validated local/DVC publication state across chats."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.runtime.project import find_project_root

RECEIPT = Path(".runtime/archive-assurance.json")
DATA_ROOTS = ("raw", "merged", "processed", "unified", "accounts", "external")


@dataclass(frozen=True)
class AssuranceState:
    status: str
    verified_at: str | None = None
    git_head: str | None = None
    method: str | None = None

    def compact(self) -> str:
        if self.status == "verified":
            return (
                f"Archive validated/published at {self.verified_at} "
                f"(commit {self.git_head[:8]}); local data unchanged."
            )
        if self.status == "changed":
            return (
                f"Archive baseline {self.verified_at}: local data changed afterward."
            )
        return "Archive validation record missing; run explicit verification when needed."


def _pointer_digest(root: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted((root / "data").glob("*.dvc")) + sorted((root / "data/external").glob("*.dvc"))
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _checkout_digest(root: Path) -> str:
    """Cheap drift fingerprint; content was checked by DVC at validation."""
    digest = hashlib.sha256()
    for name in DATA_ROOTS:
        base = root / "data" / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            digest.update(str(path.relative_to(root)).encode())
            digest.update(f"\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def write_assurance(root: Path, *, git_head: str, method: str) -> Path:
    """Write a compact receipt after a completed verification or push."""
    payload = {
        "version": 1,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "method": method,
        "dvc_pointer_digest": _pointer_digest(root),
        "checkout_digest": _checkout_digest(root),
    }
    target = root / RECEIPT
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n")
    os.replace(temporary, target)
    return target


def read_assurance(root: Path, *, git_head: str | None = None) -> AssuranceState:
    target = root / RECEIPT
    if not target.is_file():
        return AssuranceState("missing")
    try:
        payload = json.loads(target.read_text())
        if payload["version"] != 1:
            return AssuranceState("missing")
        changed = (
            payload["dvc_pointer_digest"] != _pointer_digest(root)
            or payload["checkout_digest"] != _checkout_digest(root)
        )
        return AssuranceState(
            "changed" if changed else "verified",
            payload["verified_at"], payload["git_head"], payload["method"],
        )
    except (OSError, ValueError, KeyError, TypeError):
        return AssuranceState("missing")


def _run(root: Path, command: list[str]) -> str:
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def verify_and_record(root: Path) -> Path:
    """Explicit deep local + remote verification, never run at chat startup."""
    from src.operations.local_freshness import inspect_archive

    freshness = inspect_archive(root)
    if freshness.status != "current":
        raise RuntimeError(freshness.compact())
    dvc = root / ".venv/bin/dvc"
    if "up to date" not in _run(root, [str(dvc), "status"]).lower():
        raise RuntimeError("DVC working data does not match its pointers")
    if "in sync" not in _run(root, [str(dvc), "status", "--cloud"]).lower():
        raise RuntimeError("DVC cache and remote are not in sync")
    head = _run(root, ["git", "rev-parse", "HEAD"])
    origin = _run(root, ["git", "rev-parse", "origin/main"])
    if head != origin:
        raise RuntimeError("Git HEAD is not the published origin/main")
    return write_assurance(root, git_head=head, method="verified_cloud")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "verify"), nargs="?", default="status")
    args = parser.parse_args()
    root = find_project_root(Path(__file__))
    if args.action == "verify":
        try:
            verify_and_record(root)
        except RuntimeError as exc:
            print(f"Archive validation not recorded: {exc}")
            return 1
    print(read_assurance(root).compact())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
