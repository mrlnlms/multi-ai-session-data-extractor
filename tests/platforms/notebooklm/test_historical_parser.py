"""Tests for first-class parsing of frozen NotebookLM snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.platforms.notebooklm.parser import NotebookLMParser
from src.platforms.notebooklm.historical_parser import (
    HISTORICAL_CAPTURE_METHOD,
    parse_historical_archives,
)
from src.platforms.notebooklm.commands import parse as notebooklm_parse_script

def _write_historical_snapshot(
    root: Path, archive_name: str = "former-work-account-2026-01-02"
) -> Path:
    archive = root / archive_name
    notebook = archive / "notebook-1"
    assets = notebook / "audio"
    assets.mkdir(parents=True)
    (notebook / "notebook.json").write_text(
        json.dumps(
            {
                "uuid": "notebook-1",
                "title": "Historical notebook",
                "sources": [{"uuid": "source-1", "name": "source.pdf"}],
                "guide": {
                    "summary": "Historical summary",
                    "questions": ["What changed?"],
                },
            }
        ),
        encoding="utf-8",
    )
    (notebook / "chat.json").write_text(
        json.dumps(
            [
                {"role": "user", "content": "Question without upstream access"},
                {"role": "assistant", "content": "Preserved answer"},
            ]
        ),
        encoding="utf-8",
    )
    (assets / "brief-1_brief.md").write_text("# Historical brief\n\nBody", encoding="utf-8")
    (assets / "overview.m4a").write_bytes(b"historical audio")
    return archive


def _ids(result) -> dict[str, list[str]]:
    return {
        "conversations": [item.conversation_id for item in result.conversations],
        "messages": [item.message_id for item in result.messages],
        "branches": [item.branch_id for item in result.branches],
        "sources": [item.doc_id for item in result.sources],
        "notes": [item.note_id for item in result.notes],
        "outputs": [item.output_id for item in result.outputs],
        "questions": [item.question_id for item in result.guide_questions],
    }


def test_historical_snapshot_has_stable_provenance_and_ids(tmp_path):
    root = tmp_path / "snapshots"
    _write_historical_snapshot(root)

    first = parse_historical_archives(root)
    second = parse_historical_archives(root)

    assert _ids(first) == _ids(second)
    assert len(first.conversations) == 1
    assert len(first.messages) == 3  # guide summary plus two chat turns
    assert len(first.sources) == 1
    assert len(first.notes) == 1
    assert len(first.outputs) == 1
    assert len(first.guide_questions) == 1
    assert first.conversations[0].account == "archive:former-work-account-2026-01-02"
    assert first.conversations[0].capture_method == HISTORICAL_CAPTURE_METHOD
    assert all(
        message.account == "archive:former-work-account-2026-01-02"
        for message in first.messages
    )
    assert first.conversations[0].created_at == pd.Timestamp("2026-01-02", tz="UTC")


def test_official_parser_combines_live_and_historical_rows(tmp_path):
    root = tmp_path / "snapshots"
    _write_historical_snapshot(root)
    historical = parse_historical_archives(root)

    NotebookLMParser().parse(
        {"notebooks": [], "sources": {}, "source_guides": {}},
        output_dir=tmp_path / "processed",
        historical=historical,
    )

    output = tmp_path / "processed"
    conversations = pd.read_parquet(output / "notebooklm_conversations.parquet")
    messages = pd.read_parquet(output / "notebooklm_messages.parquet")
    outputs = pd.read_parquet(output / "notebooklm_outputs.parquet")

    assert len(conversations) == 1
    assert set(conversations["capture_method"]) == {HISTORICAL_CAPTURE_METHOD}
    assert len(messages) == 3
    assert len(outputs) == 1


def test_multiple_archives_get_distinct_stable_accounts(tmp_path):
    root = tmp_path / "snapshots"
    _write_historical_snapshot(root, "former-work-account-2026-01-02")
    _write_historical_snapshot(root, "retired-personal-account-2026-02-03")

    result = parse_historical_archives(root)

    assert {item.account for item in result.conversations} == {
        "archive:former-work-account-2026-01-02",
        "archive:retired-personal-account-2026-02-03",
    }
    assert len({item.conversation_id for item in result.conversations}) == 2


def test_empty_or_missing_snapshot_root_fails_closed(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir()
    try:
        parse_historical_archives(root)
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("an empty configured archive root must fail")

    missing = tmp_path / "missing"
    try:
        parse_historical_archives(missing)
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("missing configured archive root must fail")


def test_official_command_does_not_write_when_archive_root_is_missing(tmp_path):
    merged = tmp_path / "merged"
    merged.mkdir()
    output = tmp_path / "processed"

    result = notebooklm_parse_script.main(
        [
            "--merged-root",
            str(merged),
            "--historical-root",
            str(tmp_path / "missing"),
            "--output-dir",
            str(output),
            "--accounts-file",
            str(tmp_path / "accounts.json"),
        ]
    )

    assert result == 1
    assert not output.exists()


def test_official_command_requires_explicit_opt_out_for_current_only(tmp_path):
    merged = tmp_path / "merged"
    merged.mkdir()
    output = tmp_path / "processed"

    result = notebooklm_parse_script.main(
        [
            "--merged-root",
            str(merged),
            "--historical-root",
            str(tmp_path / "missing"),
            "--output-dir",
            str(output),
            "--accounts-file",
            str(tmp_path / "accounts.json"),
            "--without-historical",
        ]
    )

    assert result == 0
    assert (output / "notebooklm_conversations.parquet").is_file()


def test_malformed_historical_notebook_fails_closed(tmp_path):
    root = tmp_path / "snapshots"
    archive = root / "former-work-account-2026-01-02" / "notebook-1"
    archive.mkdir(parents=True)
    (archive / "notebook.json").write_text("{not json", encoding="utf-8")

    try:
        parse_historical_archives(root)
    except ValueError:
        pass
    else:
        raise AssertionError("a malformed historical notebook must stop the rebuild")
