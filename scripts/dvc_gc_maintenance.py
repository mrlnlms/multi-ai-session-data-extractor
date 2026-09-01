#!/usr/bin/env python3
"""Deliberate, resumable DVC cloud-GC maintenance for the current data state.

This exists because Google Drive is a slow DVC object store: DVC's native GC
deletes objects one at a time and an individual HTTP response can hang.  The
tool keeps DVC's own dry-run as the source of truth, persists its plan under
``.runtime/`` and puts a deadline on each Drive request.

It is intentionally *not* part of collection or publishing.  Applying a plan
deletes historical DVC objects from the configured remote and therefore always
requires the explicit ``--apply`` switch.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dvc.fs import get_cloud_fs
from dvc.repo import Repo


DEFAULT_REMOTE = "gdrive_remote"
DEFAULT_BATCH_SIZE = 500
DEFAULT_REQUEST_TIMEOUT = 120
RUNTIME_ROOT = Path(".runtime/dvc-gc")


class RequestTimedOut(TimeoutError):
    """A single Drive deletion exceeded the selected deadline."""


class request_deadline:
    """Interrupt one synchronous request without affecting later requests."""

    def __init__(self, seconds: int):
        self.seconds = seconds
        self.previous_handler: Any = None

    def __enter__(self) -> None:
        self.previous_handler = signal.getsignal(signal.SIGALRM)

        def raise_timeout(_signum: int, _frame: Any) -> None:
            raise RequestTimedOut(f"request exceeded {self.seconds}s")

        signal.signal(signal.SIGALRM, raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)

    def __exit__(self, *_exc: Any) -> None:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.previous_handler)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def atomic_json_write(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def candidates_from_dvc_output(output: str) -> list[str]:
    """Extract only paths printed by DVC's normal dry-run output."""
    return [
        line.removeprefix("Removing ").strip()
        for line in output.splitlines()
        if line.startswith("Removing ")
    ]


def clean_status(output: str) -> bool:
    """Return whether DVC says there is no local or cloud divergence."""
    normalized = output.lower()
    return "up to date" in normalized or "are in sync" in normalized


def run_dvc(arguments: list[str], *, check: bool = True) -> str:
    command = [sys.executable, "-m", "dvc", *arguments]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    output = result.stdout + result.stderr
    if check and result.returncode:
        raise RuntimeError(f"DVC failed ({result.returncode}):\n{output}")
    return output


def preflight(remote: str, *, cloud: bool) -> None:
    local = run_dvc(["status"])
    if not clean_status(local):
        raise RuntimeError(
            "Workspace DVC is not current. Publish/resolve it before a GC.\n" + local
        )
    if cloud:
        remote_status = run_dvc(["status", "--cloud", "--remote", remote])
        if not clean_status(remote_status):
            raise RuntimeError(
                "Cache and remote are not in sync. Run and validate dvc push first.\n"
                + remote_status
            )


def configured_remote(remote_name: str) -> tuple[Any, str]:
    repo = Repo(".")
    fs_cls, config, root = get_cloud_fs(repo.config, name=remote_name)
    return fs_cls(**config), root


def expected_prefix(root: str) -> str:
    return f"{root.rstrip('/')}/files/md5/"


def validate_candidates(candidates: list[str], prefix: str) -> None:
    outside = [path for path in candidates if not path.startswith(prefix)]
    if outside:
        raise ValueError(
            "DVC dry-run emitted path(s) outside the configured MD5 object root: "
            + ", ".join(outside[:3])
        )


def current_git_head() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def new_run_directory() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = RUNTIME_ROOT / stamp
    suffix = 1
    while directory.exists():
        directory = RUNTIME_ROOT / f"{stamp}-{suffix}"
        suffix += 1
    return directory


def create_plan(remote: str, run_directory: Path | None = None) -> Path:
    """Freeze a reviewed DVC dry-run after confirming current data is pushed."""
    preflight(remote, cloud=True)
    _fs, root = configured_remote(remote)
    prefix = expected_prefix(root)
    dry_output = run_dvc(["gc", "--workspace", "--cloud", "--dry", "--remote", remote])
    candidates = candidates_from_dvc_output(dry_output)
    validate_candidates(candidates, prefix)

    directory = run_directory or new_run_directory()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {
        "format": 1,
        "created_at": utc_now(),
        "git_head": current_git_head(),
        "remote": remote,
        "object_prefix": prefix,
        "candidates": candidates,
        "dvc_dry_output": dry_output,
    }
    progress = {
        "format": 1,
        "updated_at": utc_now(),
        "outcomes": {},
        "final_audit": None,
    }
    atomic_json_write(directory / "plan.json", plan)
    atomic_json_write(directory / "progress.json", progress)
    print(f"Plan created: {directory}")
    print(f"Candidates: {len(candidates)}")
    return directory


def append_event(directory: Path, event: dict[str, Any]) -> None:
    with (directory / "events.jsonl").open("a") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()


def unfinished_candidates(plan: dict[str, Any], progress: dict[str, Any]) -> list[str]:
    outcomes = progress["outcomes"]
    # A timeout has unknown remote state. Do not retry it blindly; a new dry-run
    # will show whether it really remains.
    return [path for path in plan["candidates"] if path not in outcomes]


def delete_one(remote: Any, path: str, timeout: int) -> tuple[str, str | None, float]:
    started = time.monotonic()
    try:
        with request_deadline(timeout):
            remote.rm_file(path)
    except RequestTimedOut as exc:
        return "timeout_unknown", str(exc), time.monotonic() - started
    except FileNotFoundError:
        return "already_absent", None, time.monotonic() - started
    except Exception as exc:  # Preserve error detail; never turn it into a blind retry.
        return "failed", f"{type(exc).__name__}: {exc}", time.monotonic() - started
    return "deleted", None, time.monotonic() - started


def run_final_audit(directory: Path, plan: dict[str, Any], progress: dict[str, Any]) -> bool:
    output = run_dvc(
        ["gc", "--workspace", "--cloud", "--dry", "--remote", plan["remote"]]
    )
    remaining = candidates_from_dvc_output(output)
    validate_candidates(remaining, plan["object_prefix"])
    progress["final_audit"] = {
        "at": utc_now(),
        "remaining_candidates": len(remaining),
        "dvc_dry_output": output,
    }
    progress["updated_at"] = utc_now()
    atomic_json_write(directory / "progress.json", progress)
    print(f"Final DVC dry-run: {len(remaining)} candidate(s) still present.")
    if not remaining:
        cloud_status = run_dvc(["status", "--cloud", "--remote", plan["remote"]])
        if not clean_status(cloud_status):
            raise RuntimeError("Post-GC cloud status is not in sync.\n" + cloud_status)
        print("Maintenance complete: current data is synchronized and no historical GC candidates remain.")
        return True
    print(f"Review {directory / 'progress.json'} before creating a new plan for the remaining objects.")
    return False


def apply_plan(directory: Path, batch_size: int, request_timeout: int, max_batches: int | None) -> bool:
    plan_path = directory / "plan.json"
    progress_path = directory / "progress.json"
    if not plan_path.is_file() or not progress_path.is_file():
        raise ValueError(f"Not a GC maintenance run directory: {directory}")
    plan = read_json(plan_path)
    progress = read_json(progress_path)
    validate_candidates(plan["candidates"], plan["object_prefix"])
    preflight(plan["remote"], cloud=True)
    remote, root = configured_remote(plan["remote"])
    if expected_prefix(root) != plan["object_prefix"]:
        raise RuntimeError("Configured remote root changed since this plan was created.")

    pending = unfinished_candidates(plan, progress)
    batches_done = 0
    while pending and (max_batches is None or batches_done < max_batches):
        batch = pending[:batch_size]
        batches_done += 1
        print(f"Batch {batches_done}: {len(batch)} object(s); {len(pending)} pending.", flush=True)
        for index, path in enumerate(batch, start=1):
            status, detail, elapsed = delete_one(remote, path, request_timeout)
            record = {"status": status, "at": utc_now(), "elapsed_seconds": round(elapsed, 3)}
            if detail:
                record["detail"] = detail
            progress["outcomes"][path] = record
            progress["updated_at"] = utc_now()
            atomic_json_write(progress_path, progress)
            append_event(directory, {"path": path, **record})
            print(f"  {index}/{len(batch)} {status} {elapsed:.1f}s {path}", flush=True)
        # A local data change invalidates the maintenance decision; stop before
        # the next batch rather than continuing against a changed workspace.
        preflight(plan["remote"], cloud=False)
        pending = unfinished_candidates(plan, progress)

    if pending:
        print(f"Paused with {len(pending)} unattempted object(s). Resume this same run directory.")
        return False
    return run_final_audit(directory, plan, progress)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="preflight and write a non-destructive GC plan")
    plan.add_argument("--remote", default=DEFAULT_REMOTE)

    run = commands.add_parser("run", help="create and execute a new plan")
    run.add_argument("--remote", default=DEFAULT_REMOTE)
    run.add_argument("--apply", action="store_true", help="required: permit remote object deletion")
    run.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    run.add_argument("--request-timeout", type=int, default=DEFAULT_REQUEST_TIMEOUT)
    run.add_argument("--max-batches", type=int, help="stop after this many batches (for a bounded run)")

    resume = commands.add_parser("resume", help="continue an existing plan")
    resume.add_argument("run_directory", type=Path)
    resume.add_argument("--apply", action="store_true", help="required: permit remote object deletion")
    resume.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    resume.add_argument("--request-timeout", type=int, default=DEFAULT_REQUEST_TIMEOUT)
    resume.add_argument("--max-batches", type=int, help="stop after this many batches")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "plan":
        create_plan(args.remote)
        return 0
    if not args.apply:
        raise SystemExit("Refusing to delete remote DVC objects without --apply.")
    if args.batch_size < 1 or args.request_timeout < 1:
        raise SystemExit("--batch-size and --request-timeout must be positive.")
    if args.max_batches is not None and args.max_batches < 1:
        raise SystemExit("--max-batches must be positive.")
    if args.command == "run":
        directory = create_plan(args.remote)
    else:
        directory = args.run_directory
    return 0 if apply_plan(directory, args.batch_size, args.request_timeout, args.max_batches) else 1


if __name__ == "__main__":
    raise SystemExit(main())
