import json
from datetime import datetime, timezone

import pytest

from src.account_catalog import (
    LifecycleStatus,
    legacy_account_id,
    load_account_catalog,
    serialize_account_catalog,
    write_account_catalog_atomic,
)


def _record(**overrides):
    record = {
        "account_id": legacy_account_id("Qwen", "default"),
        "platform": "Qwen",
        "technical_key": "default",
        "lifecycle_status": "historical",
        "created_at": "2026-09-13T00:00:00Z",
        "updated_at": "2026-09-13T00:00:00Z",
    }
    record.update(overrides)
    return record


def _write_catalog(tmp_path, *, version=1, accounts=None):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "version": version,
        "accounts": [_record()] if accounts is None else accounts,
    }))
    return path


def test_missing_catalog_is_empty(tmp_path):
    assert load_account_catalog(tmp_path / "missing.json").records == ()


def test_catalog_loads_exact_lifecycle_and_immutable_id(tmp_path):
    account_id = legacy_account_id("Qwen", "default")
    record = load_account_catalog(_write_catalog(tmp_path)).records[0]

    assert record.lifecycle_status is LifecycleStatus.HISTORICAL
    assert record.account_id == account_id
    with pytest.raises((AttributeError, TypeError)):
        record.technical_key = "other"


def test_legacy_account_id_is_stable_and_namespaced():
    assert legacy_account_id("Qwen", "default") == legacy_account_id("Qwen", "default")
    assert legacy_account_id("Qwen", "default") != legacy_account_id("ChatGPT", "default")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"version": 2, "accounts": []}, "version"),
        ({"version": 1, "accounts": "invalid"}, "accounts"),
        ({"version": 1, "accounts": [_record(account_id="not-a-uuid")]}, "UUID"),
        ({"version": 1, "accounts": [_record(platform="Unsupported")]}, "platform"),
        ({"version": 1, "accounts": [_record(technical_key="")]}, "technical_key"),
        ({"version": 1, "accounts": [_record(created_at="not-a-date")]}, "created_at"),
        ({"version": 1, "accounts": [_record(updated_at="2026-09-13T00:00:00")]}, "updated_at"),
        ({"version": 1, "accounts": [_record(lifecycle_status="unknown")]}, "lifecycle_status"),
    ],
)
def test_invalid_catalog_fields_are_rejected(tmp_path, payload, message):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match=message):
        load_account_catalog(path)


def test_duplicate_account_id_is_rejected(tmp_path):
    duplicate = _record(platform="ChatGPT", technical_key="default")
    with pytest.raises(ValueError, match="Duplicate account_id"):
        load_account_catalog(_write_catalog(tmp_path, accounts=[_record(), duplicate]))


def test_duplicate_platform_and_technical_key_is_rejected(tmp_path):
    duplicate = _record(account_id=legacy_account_id("Qwen", "second-id"))
    with pytest.raises(ValueError, match="Duplicate account identity"):
        load_account_catalog(_write_catalog(tmp_path, accounts=[_record(), duplicate]))


def test_catalog_root_and_record_fields_are_strict(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="root"):
        load_account_catalog(path)

    with pytest.raises(ValueError, match="fields"):
        load_account_catalog(_write_catalog(tmp_path, accounts=[_record(extra="value")]))


def test_canonical_serializer_and_atomic_stale_write(tmp_path):
    path = _write_catalog(tmp_path)
    before = load_account_catalog(path)
    serialized = serialize_account_catalog(before)
    assert serialized.endswith("\n")
    assert json.loads(serialized)["accounts"][0]["created_at"].endswith("Z")

    after = type(before)(records=())
    path.write_text(json.dumps({"version": 1, "accounts": []}))
    with pytest.raises(ValueError, match="stale"):
        write_account_catalog_atomic(path, after, expected_before=before)
