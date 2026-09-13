"""UI-neutral contracts and persistence for the four-stage pipeline."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime.project import find_project_root
from src.workflows.execution import (
    acquire_pipeline_lock,
    quarto_installed,
    release_pipeline_lock,
    run_publish_streaming,
    run_quarto_streaming,
    run_sync_streaming,
    run_unify_streaming,
)

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

# Stable dependency aliases make the orchestration independently testable and
# keep presentation adapters away from subprocess and lock implementation.
acquire_lock = acquire_pipeline_lock
release_lock = release_pipeline_lock
run_sync = run_sync_streaming
run_unify = run_unify_streaming
has_quarto = quarto_installed
run_quarto = run_quarto_streaming
run_publish = run_publish_streaming


@dataclass(frozen=True)
class PipelineRequest:
    platforms: tuple[str, ...]
    publish_after: bool
    scope: str = "all"


@dataclass(frozen=True)
class PipelineEvent:
    kind: str
    stage_index: int | None = None
    status: str | None = None
    platform: str | None = None
    line: str | None = None
    completed: int | None = None
    total: int | None = None
    message: str | None = None
    level: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    stage_status: tuple[str, ...]
    results: tuple[dict[str, Any], ...]
    lock_error: str | None = None


def run_pipeline(
    request: PipelineRequest,
    emit: Callable[[PipelineEvent], None] | None = None,
) -> PipelineResult:
    """Run the operational pipeline without depending on a presentation layer."""
    notify = emit or (lambda event: None)
    lock_error = acquire_lock()
    if lock_error:
        notify(PipelineEvent("lock_error", message=lock_error, level="error"))
        return PipelineResult(tuple(["pending"] * 4), (), lock_error)

    statuses = ["pending"] * 4
    if not request.publish_after:
        statuses[3] = "skipped"
    results: list[dict[str, Any]] = []

    def set_stage(index: int, status: str) -> None:
        statuses[index] = status
        notify(PipelineEvent("stage_status", stage_index=index, status=status))

    def add_result(
        stage_index: int,
        step: str,
        status: str,
        detail: str = "",
        tail: str = "",
    ) -> None:
        results.append(
            {
                "stage": STAGE_KEYS[stage_index],
                "step": step,
                "status": status,
                "detail": detail,
                "tail": tail,
            }
        )
        notify(
            PipelineEvent(
                "step_result",
                stage_index=stage_index,
                status=status,
                platform=step if stage_index == 0 else None,
                message=detail,
            )
        )

    def finish() -> PipelineResult:
        persist_run(statuses, results, request.publish_after, request.scope)
        outcome = PipelineResult(tuple(statuses), tuple(results))
        notify(PipelineEvent("finished"))
        return outcome

    try:
        notify(PipelineEvent("started", total=len(request.platforms)))
        set_stage(0, "running")
        any_sync_ok = False
        any_sync_fail = False
        for index, platform in enumerate(request.platforms):
            def on_sync_line(line: str, name: str = platform) -> None:
                notify(
                    PipelineEvent(
                        "output",
                        stage_index=0,
                        platform=name,
                        line=line,
                        completed=index,
                        total=len(request.platforms),
                    )
                )

            try:
                rc, tail = run_sync(platform, on_line=on_sync_line)
            except Exception as exc:  # noqa: BLE001
                rc, tail = -1, f"exception: {exc}"
            ok = rc == 0
            any_sync_ok |= ok
            any_sync_fail |= not ok
            add_result(
                0,
                platform,
                "ok" if ok else "failed",
                "" if ok else f"rc={rc}",
                tail[-10000:],
            )
            notify(
                PipelineEvent(
                    "sync_progress",
                    stage_index=0,
                    platform=platform,
                    completed=index + 1,
                    total=len(request.platforms),
                )
            )

        if not any_sync_ok:
            set_stage(0, "failed")
            for index, step in ((1, "abort"), (2, "quarto-render")):
                set_stage(index, "aborted")
                add_result(index, step, "aborted", "all stage 1 platforms failed")
            if request.publish_after:
                set_stage(3, "aborted")
                add_result(3, "abort", "aborted", "all stage 1 platforms failed")
            return finish()
        set_stage(0, "failed" if any_sync_fail else "done")

        notify(PipelineEvent("stage_started", stage_index=1))
        set_stage(1, "running")
        try:
            rc, tail = run_unify(
                lambda line: notify(PipelineEvent("output", stage_index=1, line=line))
            )
        except Exception as exc:  # noqa: BLE001
            rc, tail = -1, f"exception: {exc}"
        if rc != 0:
            add_result(1, "unify-parquets", "failed", f"rc={rc}", tail[-10000:])
            set_stage(1, "failed")
            set_stage(2, "aborted")
            add_result(2, "quarto-render", "aborted", "stage 2 unify failed")
            if request.publish_after:
                set_stage(3, "aborted")
                add_result(3, "publish", "aborted", "stage 2 unify failed")
            return finish()
        add_result(1, "unify-parquets", "ok")
        set_stage(1, "done")

        quarto_ok = True
        notify(PipelineEvent("stage_started", stage_index=2))
        if not has_quarto():
            add_result(2, "quarto-render", "skipped", "quarto CLI not installed")
            set_stage(2, "skipped")
        else:
            set_stage(2, "running")
            platform_filter = (
                list(request.platforms)
                if request.scope.startswith("platform:")
                else None
            )
            try:
                rc, summary = run_quarto(
                    lambda line: notify(PipelineEvent("output", stage_index=2, line=line)),
                    platforms_filter=platform_filter,
                )
            except Exception as exc:  # noqa: BLE001
                rc, summary = -1, f"exception: {exc}"
            if rc != 0:
                quarto_ok = False
                add_result(2, "quarto-render", "failed", summary[:300], summary[-10000:])
                set_stage(2, "failed")
            else:
                add_result(2, "quarto-render", "ok", summary)
                set_stage(2, "done")
                notify(PipelineEvent("report_ready", stage_index=2))

        notify(PipelineEvent("stage_started", stage_index=3))
        if not request.publish_after:
            add_result(3, "publish", "skipped", "checkbox unchecked")
        elif not quarto_ok:
            add_result(3, "publish", "aborted", "stage 3 quarto failed")
            set_stage(3, "aborted")
        else:
            set_stage(3, "running")
            try:
                rc, summary = run_publish(
                    lambda line: notify(PipelineEvent("output", stage_index=3, line=line)),
                    commit_msg=commit_msg_for_scope(request.scope),
                )
            except Exception as exc:  # noqa: BLE001
                rc, summary = -1, f"exception: {exc}"
            if rc != 0:
                add_result(3, "publish", "failed", summary[:200], summary[-10000:])
                set_stage(3, "failed")
            else:
                add_result(3, "publish", "ok", summary)
                set_stage(3, "done")
        return finish()
    finally:
        release_lock()


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
