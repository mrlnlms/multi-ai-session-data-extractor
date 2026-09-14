import json
from datetime import datetime, timezone

import pytest

from src.account_bindings import (
    AccountBinding, AccountBindings, load_account_bindings,
    serialize_account_bindings, set_account_binding, write_account_bindings_atomic,
)

ACCOUNT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def test_missing_is_empty_and_roundtrip_is_private(tmp_path):
    path = tmp_path / "bindings.json"
    before = load_account_bindings(path)
    binding = AccountBinding(ACCOUNT_ID, "work", NOW)
    after = set_account_binding(before, binding)
    serialized = serialize_account_bindings(after)
    assert "work" in serialized
    assert not any(term in serialized.lower() for term in ("email", "cookie", "token", "/users/"))
    write_account_bindings_atomic(path, after, expected_before=before)
    assert load_account_bindings(path) == after


@pytest.mark.parametrize("payload", [
    {"version": 2, "bindings": []},
    {"version": 1, "bindings": [{"account_id": "bad", "profile_key": "work", "updated_at": "2026-09-13T00:00:00Z"}]},
    {"version": 1, "bindings": [{"account_id": ACCOUNT_ID, "profile_key": "../work", "updated_at": "2026-09-13T00:00:00Z"}]},
    {"version": 1, "bindings": [{"account_id": ACCOUNT_ID, "profile_key": "work", "updated_at": "2026-09-13T00:00:00"}]},
])
def test_invalid_bindings_fail_loudly(tmp_path, payload):
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_account_bindings(path)


def test_duplicate_and_stale_writes_are_rejected(tmp_path):
    item = {"account_id": ACCOUNT_ID, "profile_key": "work", "updated_at": "2026-09-13T00:00:00Z"}
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps({"version": 1, "bindings": [item, item]}))
    with pytest.raises(ValueError, match="Duplicate"):
        load_account_bindings(path)
