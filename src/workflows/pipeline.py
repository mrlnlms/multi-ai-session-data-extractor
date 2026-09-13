"""UI-neutral contracts and persistence for the four-stage pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.runtime.project import find_project_root

PROJECT_ROOT = find_project_root(Path(__file__))
RUNS_LOG = PROJECT_ROOT / ".runtime" / "pipeline-runs.jsonl"
MAX_RUNS_BEFORE_ROTATE = 1000
KEEP_RUNS_AFTER_ROTATE = 500

STAGE_NAMES: list[str] = [
    "Sync + parse platforms",
    "Unify parquets",
    "Quarto render",
    "Publish (DVC + git)",
]
STAGE_KEYS: list[str] = [
    f"{index + 1}/{len(STAGE_NAMES)} {name.split()[0]}"
    for index, name in enumerate(STAGE_NAMES)
]


def persist_run(
    stage_status: list[str],
    results: list[dict],
    publish_after: bool,
    scope: str,
) -> None:
    """Append pipeline metadata without retaining potentially large tails."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "stage_status": list(stage_status),
        "publish": publish_after,
        "results": [{key: value for key, value in row.items() if key != "tail"} for row in results],
    }
    try:
        RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RUNS_LOG.open("a") as stream:
            stream.write(json.dumps(entry) + "\n")
        _maybe_rotate_runs_log()
    except OSError:
        pass


def _maybe_rotate_runs_log() -> None:
    try:
        with RUNS_LOG.open() as stream:
            lines = stream.readlines()
        if len(lines) <= MAX_RUNS_BEFORE_ROTATE:
            return
        with RUNS_LOG.open("w") as stream:
            stream.writelines(lines[-KEEP_RUNS_AFTER_ROTATE:])
    except OSError:
        pass


def commit_msg_for_scope(scope: str) -> str:
    """Build the data commit message associated with a pipeline scope."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if scope == "all":
        return f"data: dashboard sync (all platforms, {date})"
    if scope.startswith("platform:"):
        platform = scope.split(":", 1)[1]
        return f"data: dashboard sync ({platform}, {date})"
    if scope.startswith("cli:"):
        kind = scope.split(":", 1)[1]
        return f"data: {kind} sync ({date})"
    return f"data: pipeline sync ({scope}, {date})"


def recent_runs(limit: int = 10) -> list[dict]:
    """Read the newest valid persisted runs first."""
    if not RUNS_LOG.exists():
        return []
    entries: list[dict] = []
    try:
        with RUNS_LOG.open() as stream:
            for line in stream:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries[-limit:][::-1]
