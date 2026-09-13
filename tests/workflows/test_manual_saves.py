"""Tests for the manual-save workflow boundary."""

from __future__ import annotations

import json

from src.workflows.manual_saves import append_capture_log, run_manual_saves


def test_empty_input_produces_empty_summary_without_outputs(tmp_path):
    external = tmp_path / "external"
    processed = tmp_path / "processed"

    summary = run_manual_saves(external, processed)

    assert summary["totals"] == {
        "conversations": 0,
        "messages": 0,
        "tool_events": 0,
        "branches": 0,
        "platforms_touched": [],
    }
    assert not processed.exists()


def test_append_capture_log_writes_one_json_record(tmp_path):
    summary = {"duration_seconds": 0.0, "totals": {"conversations": 0}}

    path = append_capture_log(tmp_path / "manual-saves", summary)

    assert json.loads(path.read_text().strip()) == summary
