import json
from datetime import datetime, timezone

import pytest

from src.account_catalog import (
    AccountCatalog, AccountCatalogRecord, LifecycleStatus, legacy_account_id,
    load_account_catalog, serialize_account_catalog, write_account_catalog_atomic,
)

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def _record(**overrides):
    record = {
        "account_id": legacy_account_id("Qwen", "default"),
        "platform": "Qwen",
        "display_name": "Personal",
        "email": "owner@example.test",
        "lifecycle_status": "historical",
        "created_at": "2026-09-13T00:00:00Z",
        "updated_at": "2026-09-13T00:00:00Z",
    }
    record.update(overrides)
    return record


def _write_catalog(tmp_path, *, version=2, accounts=None):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "version": version,
        "accounts": [_record()] if accounts is None else accounts,
    }))
    return path


def test_missing_catalog_is_empty(tmp_path):
    assert load_account_catalog(tmp_path / "missing.json") == AccountCatalog()


def test_v2_catalog_round_trips_without_technical_key(tmp_path):
    catalog = load_account_catalog(_write_catalog(tmp_path))
    record = catalog.records[0]
    assert record.display_name == "Personal"
    assert record.email == "owner@example.test"
    assert record.account_id == legacy_account_id("Qwen", "default")
    payload = json.loads(serialize_account_catalog(catalog))
    assert payload["version"] == 2
    assert "technical_key" not in payload["accounts"][0]
    assert payload["accounts"][0]["created_at"].endswith("Z")


def test_v1_is_loaded_only_as_explicit_migration_compatibility(tmp_path):
    legacy = _record()
    legacy.pop("display_name")
    legacy.pop("email")
    legacy["technical_key"] = "default"
    catalog = load_account_catalog(_write_catalog(tmp_path, version=1, accounts=[legacy]))
    assert catalog.requires_identity_migration
    assert catalog.legacy_technical_key(catalog.records[0].account_id) == "default"
    assert catalog.records[0].display_name is None


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"version": 3, "accounts": []}, "version"),
        ({"version": 2, "accounts": "invalid"}, "accounts"),
        ({"version": 2, "accounts": [_record(account_id="not-a-uuid")]}, "UUID"),
        ({"version": 2, "accounts": [_record(platform="Unsupported")]}, "platform"),
        ({"version": 2, "accounts": [_record(display_name=" padded ")]}, "display_name"),
        ({"version": 2, "accounts": [_record(created_at="not-a-date")]}, "created_at"),
        ({"version": 2, "accounts": [_record(updated_at="2026-09-13T00:00:00")]}, "updated_at"),
        ({"version": 2, "accounts": [_record(lifecycle_status="unknown")]}, "lifecycle_status"),
        ({"version": 2, "accounts": [_record(technical_key="default")]}, "version 2"),
    ],
)
def test_invalid_catalog_fields_are_rejected(tmp_path, payload, message):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match=message):
        load_account_catalog(path)


def test_duplicate_account_id_is_rejected(tmp_path):
    duplicate = _record(platform="ChatGPT")
    with pytest.raises(ValueError, match="Duplicate account_id"):
        load_account_catalog(_write_catalog(tmp_path, accounts=[_record(), duplicate]))


def test_canonical_serializer_and_atomic_stale_write(tmp_path):
    path = _write_catalog(tmp_path)
    before = load_account_catalog(path)
    after = AccountCatalog(records=())
    path.write_text(json.dumps({"version": 2, "accounts": []}))
    with pytest.raises(ValueError, match="stale"):
        write_account_catalog_atomic(path, after, expected_before=before)


def test_record_is_immutable():
    record = AccountCatalogRecord(
        legacy_account_id("Qwen", "default"), "Qwen", None, None,
        LifecycleStatus.ACTIVE, NOW, NOW,
    )
    with pytest.raises((AttributeError, TypeError)):
        record.display_name = "changed"
