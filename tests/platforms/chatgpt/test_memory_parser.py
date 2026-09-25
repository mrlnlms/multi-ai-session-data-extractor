"""Account identity, version history, native dates and damaged-capture guards."""

import hashlib
import json
import sys

import pandas as pd
import pytest

from src.platforms.chatgpt.memory_parser import parse_account_memory, SURFACES

ACCOUNT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def _snapshot(root, surface, number, payload, *, complete=True, capture_time=None):
    directory = root / "_account_memory" / surface / f"capture-{number}"
    directory.mkdir(parents=True)
    filename = SURFACES[surface][0]
    content = json.dumps(payload, ensure_ascii=False).encode()
    (directory / filename).write_bytes(content)
    (directory / "capture.json").write_text(json.dumps({
        "version": 1, "source": "chatgpt", "surface": surface, "complete": complete,
        "captured_at": capture_time or f"2026-09-{number:02d}T12:00:00+00:00",
        "files": {filename: {"sha256": hashlib.sha256(content).hexdigest()}},
    }))
    return directory


def _entry(content="first", **kwargs):
    return {"id": "native/id", "content": content, **kwargs}


def test_versions_reappearance_and_empty_list_preserve_known_records(tmp_path):
    _snapshot(tmp_path, "saved_memories", 1, {"memories": [_entry()]})
    _snapshot(tmp_path, "saved_memories", 2, {"memories": [_entry("changed")]})
    _snapshot(tmp_path, "saved_memories", 3, {"memories": [_entry()]})
    result = parse_account_memory(tmp_path, ACCOUNT)
    [memory] = result.memories
    assert len(result.versions) == 2
    assert memory.content == "first"
    assert memory.memory_id == f"chatgpt:{ACCOUNT}:saved_memories/native%2Fid"
    assert not memory.is_preserved_missing
    current = next(v for v in result.versions if v.version_id == memory.current_version_id)
    assert current.first_seen_at == pd.Timestamp("2026-09-01T12:00:00Z")
    assert current.last_seen_at == pd.Timestamp("2026-09-03T12:00:00Z")
    _snapshot(tmp_path, "saved_memories", 4, {"memories": []})
    result = parse_account_memory(tmp_path, ACCOUNT)
    assert len(result.versions) == 2
    assert result.memories[0].is_preserved_missing
    assert result.memories[0].last_seen_at == pd.Timestamp("2026-09-03T12:00:00Z")


def test_native_dates_and_raw_provenance_remain_distinct(tmp_path):
    native = _entry(created_timestamp=1704067200.0, updated_at="2026-09-01",
                    last_updated={"actor": "user", "timestamp": 1788307200.0},
                    conversation_id="unverified-native-link", labels=["native"], extra={"unknown": True})
    _snapshot(tmp_path, "saved_memories", 3, {"memories": [native]})
    result = parse_account_memory(tmp_path, ACCOUNT)
    [version] = result.versions
    assert version.effective_created_at == pd.Timestamp("2024-01-01T00:00:00Z")
    assert version.created_at_basis == "native_created_timestamp"
    assert version.updated_at_basis == "native_last_updated"
    assert version.source_birth_at is None
    assert version.captured_at == pd.Timestamp("2026-09-03T12:00:00Z")
    assert {e.evidence_type for e in result.temporal_evidence} >= {
        "native_created_timestamp", "native_last_updated", "native_updated_at", "capture_observed",
    }
    for evidence in result.temporal_evidence:
        assert not evidence.is_inference
        assert evidence.account_id == ACCOUNT
        assert (tmp_path / evidence.locator.split("#")[0]).is_file()
        assert json.loads(evidence.details_json)["native_metadata"]["conversation_id"] == "unverified-native-link"


def test_missing_creation_uses_observation_with_explicit_basis(tmp_path):
    _snapshot(tmp_path, "saved_memories", 1, {"memories": [_entry(created_timestamp=None, updated_at="2025-05-29")]})
    [version] = parse_account_memory(tmp_path, ACCOUNT).versions
    assert version.created_at_basis == "first_observed"
    assert version.effective_created_at == version.first_seen_at
    assert version.source_modified_at == pd.Timestamp("2025-05-29", tz="UTC")
    assert version.updated_at_confidence == "medium"


def test_missing_field_in_later_observation_keeps_known_native_date(tmp_path):
    _snapshot(tmp_path, "saved_memories", 1, {"memories": [_entry(created_timestamp=1704067200)]})
    _snapshot(tmp_path, "saved_memories", 2, {"memories": [_entry(created_timestamp=None)]})
    [version] = parse_account_memory(tmp_path, ACCOUNT).versions
    assert version.created_at_basis == "native_created_timestamp"
    assert version.effective_created_at == pd.Timestamp("2024-01-01T00:00:00Z")


def test_summary_and_instructions_keep_complete_structured_content(tmp_path):
    summary = {"generatedAtIso": "2026-09-01T01:02:03Z", "sections": [
        {"id": "s", "description": "text", "followUps": [{"prompt": "question", "action": "action"}]}],
        "unknown": True}
    instructions = {"about_user_message": "", "enabled": False, "unknown": [1, 2]}
    _snapshot(tmp_path, "summary", 2, summary)
    _snapshot(tmp_path, "instructions", 2, instructions)
    result = parse_account_memory(tmp_path, ACCOUNT)
    by_kind = {m.kind: m for m in result.memories}
    assert json.loads(by_kind["memory_summary"].content) == summary
    assert json.loads(by_kind["account_instructions"].content) == instructions
    assert by_kind["memory_summary"].created_at == pd.Timestamp("2026-09-01T01:02:03Z")
    assert by_kind["account_instructions"].account_id == ACCOUNT


def test_incomplete_and_staging_snapshots_do_not_change_current_state(tmp_path):
    _snapshot(tmp_path, "saved_memories", 1, {"memories": [_entry()]})
    incomplete = _snapshot(tmp_path, "saved_memories", 2, {}, complete=False)
    (incomplete / "chatgpt_memories.json").write_text("corrupt incomplete file")
    staging = _snapshot(tmp_path, "saved_memories", 3, {"memories": []})
    staging.rename(staging.with_name(".capture-staging"))
    result = parse_account_memory(tmp_path, ACCOUNT)
    assert len(result.memories) == 1
    assert not result.memories[0].is_preserved_missing


def test_corrupt_complete_snapshot_stops_projection(tmp_path):
    directory = _snapshot(tmp_path, "saved_memories", 1, {"memories": [_entry()]})
    (directory / "chatgpt_memories.json").write_text('{"memories": []}')
    with pytest.raises(ValueError, match="hash mismatch"):
        parse_account_memory(tmp_path, ACCOUNT)


@pytest.mark.parametrize("payload", [
    {"memories": [{"content": "missing id"}]},
    {"memories": [_entry(), _entry()]},
    {"memories": None},
])
def test_invalid_entry_identity_fails_instead_of_dropping_records(tmp_path, payload):
    _snapshot(tmp_path, "saved_memories", 1, payload)
    with pytest.raises(ValueError):
        parse_account_memory(tmp_path, ACCOUNT)


def test_legacy_markdown_keeps_unknown_dates_and_is_not_split_into_entries(tmp_path):
    content = "# Memories\n\n- old fact\n- another"
    (tmp_path / "chatgpt_memories.md").write_text(content)
    result = parse_account_memory(tmp_path, ACCOUNT)
    [memory] = result.memories
    assert memory.kind == "legacy_export" and memory.content == content
    assert memory.created_at is None and memory.first_seen_at is None
    assert result.versions[0].created_at_confidence == "unknown"


def test_current_native_export_without_history_has_no_invented_capture_date(tmp_path):
    (tmp_path / "chatgpt_memories.json").write_text(json.dumps({"memories": [_entry()]}))
    result = parse_account_memory(tmp_path, ACCOUNT)
    assert result.memories[0].kind == "saved_memory"
    assert result.memories[0].first_seen_at is None
    assert result.memories[0].created_at is None


def test_legacy_json_adds_versions_to_known_surface_without_claiming_a_date(tmp_path):
    directory = _snapshot(tmp_path, "instructions", 1, {"enabled": True})
    old = tmp_path / "_account_memory" / "prior_exports" / "chatgpt_instructions.json"
    old.mkdir(parents=True)
    (old / "same").write_bytes((directory / "chatgpt_instructions.json").read_bytes())
    (old / "different").write_text('{"enabled": false}')
    result = parse_account_memory(tmp_path, ACCOUNT)
    assert len(result.memories) == 1 and result.memories[0].kind == "account_instructions"
    assert len(result.versions) == 2
    assert json.loads(result.memories[0].content) == {"enabled": True}
    prior = next(v for v in result.versions if json.loads(v.content) == {"enabled": False})
    assert prior.first_seen_at is None and prior.effective_created_at is None


def test_account_scoped_ids_and_reparse_are_deterministic(tmp_path):
    _snapshot(tmp_path, "saved_memories", 1, {"memories": [_entry()]})
    first = parse_account_memory(tmp_path, ACCOUNT)
    assert first == parse_account_memory(tmp_path, ACCOUNT)
    second = parse_account_memory(tmp_path, OTHER)
    assert first.memories[0].memory_id != second.memories[0].memory_id
    assert first.versions[0].version_id != second.versions[0].version_id
    assert first.temporal_evidence[0].evidence_id != second.temporal_evidence[0].evidence_id
    with pytest.raises(ValueError, match="UUID"):
        parse_account_memory(tmp_path, None)


def test_parse_command_includes_raw_only_accounts_and_all_memory_tables(tmp_path, monkeypatch):
    from src.platforms.chatgpt.commands import parse as command

    raw = tmp_path / "raw"
    merged = tmp_path / "merged"
    merged.mkdir()
    output = tmp_path / "processed"
    for account in (ACCOUNT, OTHER):
        _snapshot(raw / f"account-{account}", "saved_memories", 1, {"memories": [_entry()]})
    monkeypatch.setattr(command, "uses_legacy_account_layout", lambda path: False)
    monkeypatch.setattr(command, "account_presentation", lambda *a, **k: "account")
    monkeypatch.setattr(command, "resolve_account_id", lambda source, key, catalog: key.removeprefix("account-"))
    monkeypatch.setattr(sys, "argv", ["parse", "--merged-path", str(merged / "chatgpt_merged.json"),
                                    "--raw-root", str(raw), "--output-dir", str(output)])
    command.main()
    memories = pd.read_parquet(output / "chatgpt_agent_memories.parquet")
    assert len(memories) == 2
    assert set(memories.account_id) == {ACCOUNT, OTHER}
    versions = pd.read_parquet(output / "chatgpt_agent_memory_versions.parquet")
    assert set(memories.current_version_id) == set(versions.version_id)
    evidence = pd.read_parquet(output / "chatgpt_agent_memory_temporal_evidence.parquet")
    assert set(evidence.version_id) == set(versions.version_id)
