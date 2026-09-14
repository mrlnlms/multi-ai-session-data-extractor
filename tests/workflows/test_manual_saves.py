"""Tests for the manual-save workflow boundary."""

from __future__ import annotations

import json
import os

import pandas as pd

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


def test_manual_workflow_is_repeatable_across_file_mtime(tmp_path):
    external = tmp_path / "external"
    clipping_dir = external / "clippings-obsidian"
    terminal_dir = external / "terminal-claude-code"
    clipping_dir.mkdir(parents=True)
    terminal_dir.mkdir(parents=True)
    clipping = clipping_dir / "2025-01-02 - Stable.md"
    clipping.write_text(
        """---
source: https://chatgpt.com/c/native-id
author: ChatGPT
created: 2025-01-02
---
> pergunta

resposta
""",
        encoding="utf-8",
    )
    terminal = terminal_dir / "20250103 - Stable.txt"
    terminal.write_text("❯ pergunta\n\n⏺ Bash(pwd)\n  ⎿ resultado\n", encoding="utf-8")

    first = tmp_path / "first"
    second = tmp_path / "second"
    run_manual_saves(external, first)
    os.utime(clipping, (1_800_000_000, 1_800_000_000))
    os.utime(terminal, (1_800_000_000, 1_800_000_000))
    run_manual_saves(external, second)

    for first_path in sorted(first.glob("*/*.parquet")):
        relative = first_path.relative_to(first)
        pd.testing.assert_frame_equal(
            pd.read_parquet(first_path),
            pd.read_parquet(second / relative),
        )
