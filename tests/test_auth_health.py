import json
from datetime import datetime, timezone

import pytest

from src.auth_health import (
    AuthEvidenceMethod, AuthHealth, AuthObservation, AuthStatus, load_auth_health,
    serialize_auth_health, set_auth_observation, write_auth_health_atomic,
)

ACCOUNT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def test_missing_is_empty_and_roundtrip_supports_unknown(tmp_path):
    path = tmp_path / "health.json"
    before = load_auth_health(path)
    observation = AuthObservation(ACCOUNT_ID, AuthStatus.UNKNOWN, None, "Not checked")
    after = set_auth_observation(before, observation)
    assert json.loads(serialize_auth_health(after))["observations"][0]["checked_at"] is None
    write_auth_health_atomic(path, after, expected_before=before)
    assert load_auth_health(path) == after


@pytest.mark.parametrize("payload", [
    {"version": 3, "observations": []},
    {"version": 1, "observations": [{"account_id": "bad", "status": "unknown", "checked_at": None, "detail": "x"}]},
    {"version": 1, "observations": [{"account_id": ACCOUNT_ID, "status": "bogus", "checked_at": None, "detail": "x"}]},
    {"version": 1, "observations": [{"account_id": ACCOUNT_ID, "status": "valid", "checked_at": "2026-09-13T00:00:00", "detail": "x"}]},
])
def test_invalid_health_fails_loudly(tmp_path, payload):
    path = tmp_path / "health.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_auth_health(path)


def test_duplicate_observations_fail(tmp_path):
    item = {"account_id": ACCOUNT_ID, "status": "unknown", "checked_at": None, "detail": "x"}
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"version": 1, "observations": [item, item]}))
    with pytest.raises(ValueError, match="Duplicate"):
        load_auth_health(path)


def test_serialization_redacts_sensitive_diagnostics():
    health = AuthHealth(records=(AuthObservation(
        ACCOUNT_ID, AuthStatus.ERROR, NOW,
        "https://example.test token=secret owner@example.test",
    ),))
    serialized = serialize_auth_health(health)
    assert "secret" not in serialized
    assert "example.test" not in serialized


def test_version_one_health_migrates_completed_observations_to_probe(tmp_path):
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"version": 1, "observations": [{
        "account_id": ACCOUNT_ID, "status": "valid",
        "checked_at": "2026-09-13T00:00:00Z", "detail": "ok",
    }]}))
    record = load_auth_health(path).records[0]
    assert record.evidence_method is AuthEvidenceMethod.PROBE
    payload = json.loads(serialize_auth_health(load_auth_health(path)))
    assert payload["version"] == 2
    assert payload["observations"][0]["evidence_method"] == "probe"
