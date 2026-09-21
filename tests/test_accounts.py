import json
from datetime import datetime, timezone

import pytest

from pathlib import Path

from src.accounts import (
    AccountEvidence,
    AccountState,
    account_data_dir,
    account_command_argument,
    account_definitions,
    account_email,
    default_sync_accounts,
    discover_accounts,
    load_account_registry,
    runnable_account_keys,
)
from src.account_catalog import LifecycleStatus, legacy_account_id
from src.auth_health import AuthEvidenceMethod, AuthHealth, AuthObservation, AuthStatus, write_auth_health_atomic


def _catalog_record(platform, key, lifecycle):
    return {
        "account_id": legacy_account_id(platform, key),
        "platform": platform,
        "technical_key": key,
        "lifecycle_status": lifecycle,
        "created_at": "2026-09-13T00:00:00Z",
        "updated_at": "2026-09-13T00:00:00Z",
    }


def test_load_account_registry_returns_profile_email_mapping(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"chatgpt": {"default": "name@example.com"}}))

    assert load_account_registry(path) == {"chatgpt": {"default": "name@example.com"}}
    assert account_email("chatgpt", "default", path) == "name@example.com"


def test_missing_registry_leaves_account_unset(tmp_path):
    path = tmp_path / "missing.json"

    assert load_account_registry(path) == {}
    assert account_email("chatgpt", "default", path) is None


def test_account_data_dir_keeps_default_and_accepts_both_account_key_forms(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = Path("data/raw/ChatGPT")

    assert account_data_dir(base, "default") == base
    assert account_data_dir(base, "2") == base / "account-2"
    assert account_data_dir(base, "account-2") == base / "account-2"


def test_account_data_dir_runtime_uuid_governs_durable_path(monkeypatch):
    account_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    monkeypatch.setenv("AI_ARCHIVE_ACCOUNT_ID", account_id)
    assert account_data_dir(Path("data/raw/Qwen"), "work") == (
        Path("data/raw/Qwen") / f"account-{account_id}"
    )


def test_canonical_account_fallbacks_preserve_current_command_contracts():
    assert [item.key for item in account_definitions("Gemini")] == ["1", "2", "3"]
    assert [item.key for item in account_definitions("NotebookLM")] == ["1", "2", "3"]
    assert [item.key for item in account_definitions("ChatGPT")] == ["default"]
    assert default_sync_accounts("Gemini") == ("1", "2", "3")
    assert default_sync_accounts("NotebookLM") == ("1", "2", "3")
    assert account_command_argument("Gemini", "work") == ("--account", "work")
    assert account_command_argument("ChatGPT", "work") == ("--account", "work")
    assert account_command_argument("Claude.ai", "work") == ("--profile", "work")
    assert account_command_argument("Kimi", "account-2") == ("--account", "account-2")
    assert account_command_argument("ChatGPT", "account-2") == ("--account", "account-2")
    assert account_command_argument("Gemini", "2") == ("--account", "2")


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
        catalog_path=tmp_path / "missing-catalog.json",
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


def test_catalog_overlay_preserves_evidence_and_catalog_only_tombstone(tmp_path):
    storage = tmp_path / ".storage"
    raw = tmp_path / "raw"
    catalog_path = tmp_path / "catalog.json"
    storage.mkdir()
    (storage / "qwen-profile-default").mkdir()
    (raw / "Qwen" / "conversation.json").parent.mkdir(parents=True)
    (raw / "Qwen" / "conversation.json").write_text("{}")
    catalog_path.write_text(json.dumps({
        "version": 1,
        "accounts": [
            _catalog_record("Qwen", "default", "disabled"),
            _catalog_record("Qwen", "retired", "historical"),
        ],
    }))

    states = discover_accounts(
        "Qwen",
        storage_root=storage,
        raw_root=raw,
        merged_root=tmp_path / "merged",
        catalog_path=catalog_path,
        registry_path=storage / "missing.json",
    )
    by_key = {state.key: state for state in states}

    assert by_key["default"].lifecycle_status is LifecycleStatus.DISABLED
    assert by_key["default"].evidence.profile_present
    assert by_key["default"].evidence.raw_present
    assert by_key["retired"].lifecycle_status is LifecycleStatus.HISTORICAL
    assert by_key["retired"].evidence == AccountEvidence()


def test_uncatalogued_data_account_is_visible_and_unclassified(tmp_path):
    raw_account = tmp_path / "raw" / "Qwen" / "account-unexpected"
    raw_account.mkdir(parents=True)
    states = discover_accounts(
        "Qwen",
        storage_root=tmp_path / ".storage",
        raw_root=tmp_path / "raw",
        merged_root=tmp_path / "merged",
        catalog_path=tmp_path / "missing-catalog.json",
        registry_path=tmp_path / "missing-registry.json",
    )
    account = {state.key: state for state in states}["unexpected"]
    assert account.account_id == legacy_account_id("Qwen", "unexpected")
    assert account.lifecycle_status is None
    assert account.evidence.raw_path == raw_account


def test_missing_profile_does_not_change_active_lifecycle(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({
        "version": 1,
        "accounts": [_catalog_record("Qwen", "default", "active")],
    }))
    account = discover_accounts(
        "Qwen",
        storage_root=tmp_path / ".storage",
        raw_root=tmp_path / "raw",
        merged_root=tmp_path / "merged",
        catalog_path=catalog_path,
        registry_path=tmp_path / "missing-registry.json",
    )[0]
    assert account.lifecycle_status is LifecycleStatus.ACTIVE
    assert account.authentication == "not_configured"


def test_discovery_uses_explicit_local_health_and_evidence_method(tmp_path):
    account_id = legacy_account_id("ChatGPT", "default")
    health_path = tmp_path / "health.json"
    health = AuthHealth(records=(AuthObservation(
        account_id, AuthStatus.VALID, datetime(2026, 9, 14, tzinfo=timezone.utc),
        "visible login", AuthEvidenceMethod.OPERATOR,
    ),))
    write_auth_health_atomic(health_path, health, expected_before=AuthHealth())
    account = discover_accounts(
        "ChatGPT", storage_root=tmp_path / ".storage", raw_root=tmp_path / "raw",
        merged_root=tmp_path / "merged", catalog_path=tmp_path / "catalog.json",
        registry_path=tmp_path / "registry.json", health_path=health_path,
    )[0]
    assert account.authentication == "valid"
    assert account.authentication_method == "operator"


def test_account_models_are_immutable():
    evidence = AccountEvidence()
    state = AccountState("ChatGPT", "default", None, evidence, "not_configured")
    with pytest.raises((AttributeError, TypeError)):
        state.key = "other"


def test_runnable_accounts_keep_order_and_exclude_inactive_or_archived(monkeypatch):
    states = (
        AccountState("NotebookLM", "1", None, AccountEvidence(), "unknown", lifecycle_status=LifecycleStatus.ACTIVE),
        AccountState("NotebookLM", "uncatalogued", None, AccountEvidence(), "unknown"),
        AccountState("NotebookLM", "2", None, AccountEvidence(), "unknown", lifecycle_status=LifecycleStatus.DISABLED),
        AccountState("NotebookLM", "archive:more-design-2026-03-30", None, AccountEvidence(), "not_configured", lifecycle_status=LifecycleStatus.HISTORICAL),
        AccountState("NotebookLM", "3", None, AccountEvidence(), "unknown", lifecycle_status=LifecycleStatus.ACTIVE),
    )
    monkeypatch.setattr("src.accounts.discover_accounts", lambda _platform: states)

    assert runnable_account_keys("NotebookLM") == ("1", "uncatalogued", "3")


def test_runnable_account_uses_exact_observed_profile_suffix(tmp_path, monkeypatch):
    profile = tmp_path / ".storage" / "kimi-profile-account-2"
    profile.mkdir(parents=True)

    states = discover_accounts(
        "Kimi",
        storage_root=tmp_path / ".storage",
        raw_root=tmp_path / "raw",
        merged_root=tmp_path / "merged",
        catalog_path=tmp_path / "catalog.json",
        registry_path=tmp_path / "registry.json",
    )
    state = next(item for item in states if item.key == "2")
    monkeypatch.setattr("src.accounts.discover_accounts", lambda _platform: (state,))

    assert runnable_account_keys("Kimi") == ("account-2",)


@pytest.mark.parametrize("content", ["[]", '{"chatgpt": []}', '{"chatgpt": {"default": ""}}'])
def test_invalid_registry_is_rejected(tmp_path, content):
    path = tmp_path / "accounts.json"
    path.write_text(content)

    with pytest.raises(ValueError):
        load_account_registry(path)
