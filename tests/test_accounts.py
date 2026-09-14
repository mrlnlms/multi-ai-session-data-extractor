import json

import pytest

from pathlib import Path

from src.accounts import (
    AccountEvidence,
    AccountState,
    account_data_dir,
    account_definitions,
    account_email,
    discover_accounts,
    load_account_registry,
)


def test_load_account_registry_returns_profile_email_mapping(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"chatgpt": {"default": "name@example.com"}}))

    assert load_account_registry(path) == {"chatgpt": {"default": "name@example.com"}}
    assert account_email("chatgpt", "default", path) == "name@example.com"


def test_missing_registry_leaves_account_unset(tmp_path):
    path = tmp_path / "missing.json"

    assert load_account_registry(path) == {}
    assert account_email("chatgpt", "default", path) is None


def test_account_data_dir_keeps_default_and_accepts_both_account_key_forms():
    base = Path("data/raw/ChatGPT")

    assert account_data_dir(base, "default") == base
    assert account_data_dir(base, "2") == base / "account-2"
    assert account_data_dir(base, "account-2") == base / "account-2"


def test_canonical_account_fallbacks_preserve_current_command_contracts():
    assert [item.key for item in account_definitions("Gemini")] == ["1", "2", "3"]
    assert [item.key for item in account_definitions("NotebookLM")] == ["1", "2", "3"]
    assert [item.key for item in account_definitions("ChatGPT")] == ["default"]


def test_discovery_unions_registry_profile_and_data_evidence(tmp_path):
    storage = tmp_path / ".storage"
    raw = tmp_path / "raw"
    merged = tmp_path / "merged"
    storage.mkdir()
    (storage / "accounts.json").write_text(json.dumps({
        "chatgpt": {
            "registered": "registered@example.com",
            "duplicate": "duplicate@example.com",
        }
    }))
    (storage / "chatgpt-profile-profile-only").mkdir()
    (storage / "chatgpt-profile-duplicate").mkdir()
    (raw / "ChatGPT" / "account-data-only").mkdir(parents=True)
    (merged / "ChatGPT" / "account-duplicate").mkdir(parents=True)

    states = discover_accounts(
        "ChatGPT",
        storage_root=storage,
        raw_root=raw,
        merged_root=merged,
        registry_path=storage / "accounts.json",
    )
    by_key = {state.key: state for state in states}

    assert set(by_key) == {"default", "registered", "profile-only", "data-only", "duplicate"}
    assert by_key["registered"].evidence.registry_present
    assert by_key["profile-only"].evidence.profile_present
    assert by_key["data-only"].evidence.raw_present
    assert by_key["duplicate"].evidence.registry_present
    assert by_key["duplicate"].evidence.profile_present
    assert by_key["duplicate"].evidence.merged_present
    assert all(state.authentication in {"unknown", "not_configured"} for state in states)


def test_default_unsuffixed_tree_requires_source_artifacts(tmp_path):
    storage = tmp_path / ".storage"
    raw = tmp_path / "raw"
    merged = tmp_path / "merged"
    storage.mkdir()
    empty_raw = raw / "ChatGPT"
    empty_raw.mkdir(parents=True)
    (empty_raw / "capture_log.jsonl").touch()

    before = discover_accounts(
        "ChatGPT", storage_root=storage, raw_root=raw, merged_root=merged,
        registry_path=storage / "missing.json",
    )[0]
    assert not before.evidence.raw_present

    (empty_raw / "conversation.json").write_text("{}")
    after = discover_accounts(
        "ChatGPT", storage_root=storage, raw_root=raw, merged_root=merged,
        registry_path=storage / "missing.json",
    )[0]
    assert after.evidence.raw_path == empty_raw


def test_legacy_perplexity_profile_and_preserved_inaccessible_account(tmp_path):
    storage = tmp_path / ".storage"
    raw = tmp_path / "raw"
    merged = tmp_path / "merged"
    storage.mkdir()
    legacy = storage / "perplexity-profile"
    legacy.mkdir()
    historical = merged / "Perplexity" / "account-historical"
    historical.mkdir(parents=True)

    states = discover_accounts(
        "Perplexity", storage_root=storage, raw_root=raw, merged_root=merged,
        registry_path=storage / "missing.json",
    )
    by_key = {state.key: state for state in states}

    assert by_key["default"].evidence.profile_path == legacy
    assert by_key["default"].authentication == "unknown"
    assert by_key["historical"].evidence.merged_path == historical
    assert by_key["historical"].authentication == "not_configured"


def test_notebooklm_historical_archive_is_a_first_class_account_evidence(tmp_path):
    storage = tmp_path / ".storage"
    raw = tmp_path / "raw"
    merged = tmp_path / "merged"
    external = tmp_path / "external"
    storage.mkdir()
    archive = external / "notebooklm-snapshots" / "More Design 2026-03-30"
    archive.mkdir(parents=True)

    states = discover_accounts(
        "NotebookLM",
        storage_root=storage,
        raw_root=raw,
        merged_root=merged,
        external_root=external,
        registry_path=storage / "missing.json",
    )
    by_key = {state.key: state for state in states}

    historical = by_key["archive:more-design-2026-03-30"]
    assert historical.evidence.historical_path == archive
    assert historical.evidence.historical_present
    assert historical.authentication == "not_configured"


def test_retired_web_account_survives_without_registry_or_profile(tmp_path):
    storage = tmp_path / ".storage"
    raw = tmp_path / "raw"
    merged = tmp_path / "merged"
    storage.mkdir()
    preserved_raw = raw / "Qwen" / "account-retired"
    preserved_merged = merged / "Qwen" / "account-retired"
    preserved_raw.mkdir(parents=True)
    preserved_merged.mkdir(parents=True)

    states = discover_accounts(
        "Qwen",
        storage_root=storage,
        raw_root=raw,
        merged_root=merged,
        registry_path=storage / "missing.json",
    )
    by_key = {state.key: state for state in states}

    retired = by_key["retired"]
    assert not retired.evidence.registry_present
    assert not retired.evidence.profile_present
    assert retired.evidence.raw_path == preserved_raw
    assert retired.evidence.merged_path == preserved_merged
    assert retired.authentication == "not_configured"


def test_account_models_are_immutable():
    evidence = AccountEvidence()
    state = AccountState("ChatGPT", "default", None, evidence, "not_configured")
    with pytest.raises((AttributeError, TypeError)):
        state.key = "other"


@pytest.mark.parametrize("content", ["[]", '{"chatgpt": []}', '{"chatgpt": {"default": ""}}'])
def test_invalid_registry_is_rejected(tmp_path, content):
    path = tmp_path / "accounts.json"
    path.write_text(content)

    with pytest.raises(ValueError):
        load_account_registry(path)
