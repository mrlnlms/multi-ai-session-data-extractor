from __future__ import annotations

from src.workflows.pipeline import PipelineRequest, run_pipeline


def _fake_dependencies(**overrides):
    deps = {
        "acquire_lock": lambda: None,
        "release_lock": lambda: None,
        "run_sync": lambda platform, on_line: (0, f"{platform} ok"),
        "run_unify": lambda on_line: (0, "unify ok"),
        "has_quarto": lambda: True,
        "run_quarto": lambda on_line, platforms_filter=None: (0, "quarto ok"),
        "run_publish": lambda on_line, commit_msg=None: (0, "publish ok"),
    }
    deps.update(overrides)
    return deps


def test_run_pipeline_preserves_four_stage_success(monkeypatch):
    from src.workflows import pipeline

    for name, value in _fake_dependencies().items():
        monkeypatch.setattr(pipeline, name, value)

    result = run_pipeline(PipelineRequest(("ChatGPT",), True, "platform:ChatGPT"))

    assert result.stage_status == ("done", "done", "done", "done")
    assert [row["step"] for row in result.results] == [
        "ChatGPT", "unify-parquets", "quarto-render", "publish",
    ]


def test_run_pipeline_skips_publish_when_disabled(monkeypatch):
    from src.workflows import pipeline

    def fail_publish(*args, **kwargs):
        raise AssertionError("publish must not run")

    for name, value in _fake_dependencies(run_publish=fail_publish).items():
        monkeypatch.setattr(pipeline, name, value)

    result = run_pipeline(PipelineRequest(("Codex",), False, "platform:Codex"))

    assert result.stage_status == ("done", "done", "done", "skipped")
    assert result.results[-1]["status"] == "skipped"


def test_run_pipeline_aborts_after_all_syncs_fail(monkeypatch):
    from src.workflows import pipeline

    for name, value in _fake_dependencies(
        run_sync=lambda platform, on_line: (1, "capture failed"),
    ).items():
        monkeypatch.setattr(pipeline, name, value)

    result = run_pipeline(PipelineRequest(("ChatGPT", "Claude.ai"), True, "all"))

    assert result.stage_status == ("failed", "aborted", "aborted", "aborted")
    assert all(row["status"] == "failed" for row in result.results[:2])


def test_run_pipeline_continues_after_partial_sync_failure(monkeypatch):
    from src.workflows import pipeline

    def sync(platform, on_line):
        return (1, "failed") if platform == "ChatGPT" else (0, "ok")

    for name, value in _fake_dependencies(run_sync=sync).items():
        monkeypatch.setattr(pipeline, name, value)

    result = run_pipeline(PipelineRequest(("ChatGPT", "Claude.ai"), False, "all"))

    assert result.stage_status == ("failed", "done", "done", "skipped")


def test_run_pipeline_aborts_quarto_and_publish_after_unify_failure(monkeypatch):
    from src.workflows import pipeline

    for name, value in _fake_dependencies(
        run_unify=lambda on_line: (2, "unify failed"),
    ).items():
        monkeypatch.setattr(pipeline, name, value)

    result = run_pipeline(PipelineRequest(("Codex",), True, "platform:Codex"))

    assert result.stage_status == ("done", "failed", "aborted", "aborted")
    assert result.results[-1]["detail"] == "stage 2 unify failed"


def test_run_pipeline_allows_publish_when_quarto_is_unavailable(monkeypatch):
    from src.workflows import pipeline

    calls = []
    for name, value in _fake_dependencies(
        has_quarto=lambda: False,
        run_publish=lambda on_line, commit_msg=None: (calls.append(commit_msg) or 0, "ok"),
    ).items():
        monkeypatch.setattr(pipeline, name, value)

    result = run_pipeline(PipelineRequest(("Codex",), True, "platform:Codex"))

    assert result.stage_status == ("done", "done", "skipped", "done")
    assert calls and "Codex" in calls[0]


def test_run_pipeline_aborts_publish_after_quarto_failure(monkeypatch):
    from src.workflows import pipeline

    def fail_publish(*args, **kwargs):
        raise AssertionError("publish must not run")

    for name, value in _fake_dependencies(
        run_quarto=lambda on_line, platforms_filter=None: (1, "render failed"),
        run_publish=fail_publish,
    ).items():
        monkeypatch.setattr(pipeline, name, value)

    result = run_pipeline(PipelineRequest(("Codex",), True, "platform:Codex"))

    assert result.stage_status == ("done", "done", "failed", "aborted")
    assert result.results[-1]["detail"] == "stage 3 quarto failed"


def test_run_pipeline_releases_lock_after_exception(monkeypatch):
    from src.workflows import pipeline

    releases = []
    for name, value in _fake_dependencies(
        release_lock=lambda: releases.append(True),
        run_unify=lambda on_line: (_ for _ in ()).throw(RuntimeError("boom")),
    ).items():
        monkeypatch.setattr(pipeline, name, value)

    result = run_pipeline(PipelineRequest(("Codex",), False, "platform:Codex"))

    assert result.stage_status[1] == "failed"
    assert releases == [True]


def test_run_pipeline_reports_busy_lock_without_running(monkeypatch):
    from src.workflows import pipeline

    for name, value in _fake_dependencies(acquire_lock=lambda: "already running").items():
        monkeypatch.setattr(pipeline, name, value)

    events = []
    result = run_pipeline(
        PipelineRequest(("Codex",), False, "platform:Codex"),
        emit=events.append,
    )

    assert result.lock_error == "already running"
    assert events[-1].kind == "lock_error"
