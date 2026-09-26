"""Classic Claude exports remain distinct from current Melange topics."""

import json
import sys

import pandas as pd
import pytest

from src.platforms.claude_ai.commands import parse as parse_command
from src.platforms.claude_ai.historical_memory import parse_historical_memory


ACCOUNT_ID = "c82fa08b-228f-58a6-bf5d-003e816ada41"
USER_ID = "5178c772-13c5-4b6c-8d39-7789ee37f566"
PROJECT_ID = "01998bf0-4bad-7466-ba23-97b6bd7e995c"


def _catalog(path):
    path.write_text(json.dumps({
        "version": 2,
        "accounts": [{
            "account_id": ACCOUNT_ID, "platform": "Claude.ai",
            "display_name": "Fixture", "email": "fixture@example.test",
            "lifecycle_status": "active",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }],
    }))


def _snapshot(root, date, *, account_memory="account v1", project_memory="project v1",
              account_uuid=USER_ID):
    directory = root / date
    directory.mkdir(parents=True)
    (directory / "users.json").write_text(json.dumps([{
        "uuid": USER_ID, "email_address": "fixture@example.test",
    }]))
    (directory / "memories.json").write_text(json.dumps([{
        "account_uuid": account_uuid,
        "conversations_memory": account_memory,
        "project_memories": {PROJECT_ID: project_memory},
    }]))


def test_historical_classic_project_and_account_memory_are_versioned_separately(tmp_path):
    root = tmp_path / "claude-ai-snapshots"
    catalog = tmp_path / "catalog.json"
    _catalog(catalog)
    _snapshot(root, "2026-03-26")
    _snapshot(root, "2026-03-30", account_memory="account v2")
    _snapshot(root, "2026-04-18", account_memory="account v2")

    result = parse_historical_memory(root, catalog)
    assert len(result.memories) == 2
    assert len(result.versions) == 3
    assert len(result.temporal_evidence) == 6
    project = next(memory for memory in result.memories if memory.project_key)
    account = next(memory for memory in result.memories if not memory.project_key)
    assert project.kind == account.kind == "legacy_export"
    assert project.project_key == PROJECT_ID
    assert project.content == "project v1"
    assert account.content == "account v2"
    assert all(memory.account_id == ACCOUNT_ID for memory in result.memories)
    assert all(not memory.is_preserved_missing for memory in result.memories)
    assert all(memory.created_at is None and memory.updated_at is None
               for memory in result.memories)
    assert all(version.source_modified_at is None and version.captured_at is None
               and version.effective_created_at is None and version.effective_updated_at is None
               for version in result.versions)
    assert {evidence.evidence_type for evidence in result.temporal_evidence} == {
        "snapshot_directory_date"
    }
    assert all(evidence.is_inference and evidence.confidence == "medium"
               for evidence in result.temporal_evidence)
    assert all("data/external/claude-ai-snapshots/" in evidence.locator
               for evidence in result.temporal_evidence)
    assert result == parse_historical_memory(root, catalog)


def test_historical_export_requires_catalogued_identity(tmp_path):
    root = tmp_path / "claude-ai-snapshots"
    catalog = tmp_path / "catalog.json"
    _catalog(catalog)
    _snapshot(root, "2026-03-26", account_uuid="other-user")
    with pytest.raises(ValueError, match="identity mismatch"):
        parse_historical_memory(root, catalog)


def test_historical_export_rejects_malformed_project_memory(tmp_path):
    root = tmp_path / "claude-ai-snapshots"
    catalog = tmp_path / "catalog.json"
    _catalog(catalog)
    _snapshot(root, "2026-03-26", project_memory={"unexpected": "shape"})
    with pytest.raises(ValueError, match="Project memory must be text"):
        parse_historical_memory(root, catalog)


def test_historical_export_does_not_silently_disappear(tmp_path):
    catalog = tmp_path / "catalog.json"
    _catalog(catalog)
    with pytest.raises(FileNotFoundError, match="Claude historical snapshots unavailable"):
        parse_historical_memory(tmp_path / "missing", catalog)


def test_official_parser_includes_history_with_explicit_opt_out(tmp_path, monkeypatch):
    root = tmp_path / "claude-ai-snapshots"
    catalog = tmp_path / "catalog.json"
    merged = tmp_path / "merged"
    raw = tmp_path / "raw"
    output = tmp_path / "processed"
    merged.mkdir()
    raw.mkdir()
    _catalog(catalog)
    _snapshot(root, "2026-03-26")

    monkeypatch.setattr(sys, "argv", [
        "parse", "--merged-root", str(merged), "--raw-root", str(raw),
        "--external-root", str(root), "--catalog-path", str(catalog),
        "--output-dir", str(output),
    ])
    parse_command.main()
    frame = pd.read_parquet(output / "claude_ai_agent_memories.parquet")
    assert len(frame) == 2
    assert set(frame["kind"]) == {"legacy_export"}

    without_history = tmp_path / "without-history"
    monkeypatch.setattr(sys, "argv", [
        "parse", "--merged-root", str(merged), "--raw-root", str(raw),
        "--external-root", str(root), "--without-historical",
        "--catalog-path", str(catalog), "--output-dir", str(without_history),
    ])
    parse_command.main()
    frame = pd.read_parquet(without_history / "claude_ai_agent_memories.parquet")
    assert frame.empty
