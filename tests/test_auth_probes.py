import inspect
import json
from datetime import datetime, timezone

import pytest

from src.account_bindings import AccountBinding, AccountBindings
from src.account_catalog import AccountCatalog, AccountCatalogRecord, LifecycleStatus
from src.auth_health import AuthStatus
from src.auth_probes import ProbeResult, check_account_auth, classify_probe_exception, redact_probe_detail

ACCOUNT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def _catalog(status=LifecycleStatus.ACTIVE, key="work"):
    return AccountCatalog(records=(AccountCatalogRecord(
        ACCOUNT_ID, "Qwen", None, None, status, NOW, NOW,
    ),))


def test_missing_binding_and_profile_are_missing(tmp_path):
    assert check_account_auth(ACCOUNT_ID, catalog=_catalog(), bindings=AccountBindings(),
                              storage_root=tmp_path).status is AuthStatus.MISSING
    bindings = AccountBindings(records=(AccountBinding(ACCOUNT_ID, "work", NOW),))
    assert check_account_auth(ACCOUNT_ID, catalog=_catalog(), bindings=bindings,
                              storage_root=tmp_path).status is AuthStatus.MISSING


def test_adapter_result_is_used_only_after_explicit_call(tmp_path, monkeypatch):
    (tmp_path / "qwen-profile-work").mkdir()
    bindings = AccountBindings(records=(AccountBinding(ACCOUNT_ID, "work", NOW),))

    async def fake_probe(key):
        assert key == "work"
        return ProbeResult(AuthStatus.VALID, "Authenticated read succeeded")

    import src.platforms.qwen.probes.auth_health as adapter
    monkeypatch.setattr(adapter, "probe", fake_probe)
    result = check_account_auth(ACCOUNT_ID, catalog=_catalog(), bindings=bindings,
                                storage_root=tmp_path)
    assert result.status is AuthStatus.VALID
    assert result.checked_at is not None


def test_auth_probe_accepts_shared_directory_without_legacy_profile(tmp_path, monkeypatch):
    storage = tmp_path / ".storage"
    shared = storage / "browser-profiles" / "personal"
    shared.mkdir(parents=True)
    group_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    groups_path = tmp_path / "browser_profiles.json"
    groups_path.write_text(json.dumps({
        "version": 1, "profiles": [{
            "profile_id": group_id, "display_name": "Personal", "email": None,
            "account_ids": [ACCOUNT_ID],
            "created_at": "2026-09-27T00:00:00Z", "updated_at": "2026-09-27T00:00:00Z",
        }],
    }))
    (storage / "browser-profile-config.json").write_text(json.dumps({
        "version": 1, "profiles": [{
            "profile_id": group_id, "channel": "chrome", "directory": "browser-profiles/personal",
        }],
    }))
    bindings = AccountBindings(records=(AccountBinding(ACCOUNT_ID, "work", NOW),))

    async def fake_probe(key):
        assert key == "work"
        return ProbeResult(AuthStatus.VALID, "Authenticated read succeeded")

    import src.platforms.qwen.probes.auth_health as adapter
    monkeypatch.setattr(adapter, "probe", fake_probe)
    result = check_account_auth(
        ACCOUNT_ID, catalog=_catalog(), bindings=bindings,
        storage_root=storage, groups_path=groups_path,
    )
    assert result.status is AuthStatus.VALID


def test_historical_unknown_and_redaction_boundaries(tmp_path):
    with pytest.raises(ValueError, match="Historical"):
        check_account_auth(ACCOUNT_ID, catalog=_catalog(LifecycleStatus.HISTORICAL),
                           bindings=AccountBindings(), storage_root=tmp_path)
    assert classify_probe_exception(RuntimeError("HTTP 401 token=secret")).status is AuthStatus.EXPIRED
    redacted = redact_probe_detail("https://example.test token=secret me@example.test")
    assert "secret" not in redacted and "example.test" not in redacted


@pytest.mark.parametrize("source", ["chatgpt", "claude_ai", "gemini", "notebooklm", "qwen", "deepseek", "perplexity", "grok", "kimi"])
def test_every_web_platform_has_probe_adapter(source):
    module = __import__(f"src.platforms.{source}.probes.auth_health", fromlist=["probe"])
    assert inspect.iscoroutinefunction(module.probe)
