from datetime import datetime, timezone

import pytest

from src.account_bindings import AccountBinding, AccountBindings, write_account_bindings_atomic
from src.account_catalog import AccountCatalog, AccountCatalogRecord, LifecycleStatus, write_account_catalog_atomic
from src.auth_health import AuthHealth, AuthObservation, AuthStatus, write_auth_health_atomic
from src.workflows.account_sync import execute_account_sync, plan_account_sync

ACCOUNT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def _state(tmp_path, lifecycle=LifecycleStatus.ACTIVE, health=AuthStatus.VALID, bound=True, profile=True):
    catalog_path, bindings_path, health_path = tmp_path / "catalog.json", tmp_path / "bindings.json", tmp_path / "health.json"
    catalog = AccountCatalog(records=(AccountCatalogRecord(ACCOUNT_ID, "Qwen", "work", lifecycle, NOW, NOW),))
    write_account_catalog_atomic(catalog_path, catalog, expected_before=AccountCatalog())
    if bound:
        bindings = AccountBindings(records=(AccountBinding(ACCOUNT_ID, "work", NOW),))
        write_account_bindings_atomic(bindings_path, bindings, expected_before=AccountBindings())
    if health:
        auth = AuthHealth(records=(AuthObservation(ACCOUNT_ID, health, NOW, "test"),))
        write_auth_health_atomic(health_path, auth, expected_before=AuthHealth())
    if profile:
        (tmp_path / "profiles" / "qwen-profile-work").mkdir(parents=True)
    return dict(catalog_path=catalog_path, bindings_path=bindings_path, health_path=health_path, storage_root=tmp_path / "profiles")


def test_active_bound_account_plans_sync_then_parse_only(tmp_path):
    plan = plan_account_sync(ACCOUNT_ID, **_state(tmp_path))
    flat = " ".join(part for command in plan.commands for part in command)
    assert "src.platforms.qwen.commands.sync --account work" in flat
    assert "src.platforms.qwen.commands.parse" in flat
    assert not any(term in flat for term in ("unify", "dvc", "git", "publish"))
    calls = []
    assert execute_account_sync(plan, runner=lambda commands: (calls.append(commands) or (0, "ok"))) == (0, "ok")
    assert calls == [plan.commands]


@pytest.mark.parametrize("lifecycle", [LifecycleStatus.DISABLED, LifecycleStatus.HISTORICAL])
def test_inactive_lifecycle_rejected(tmp_path, lifecycle):
    with pytest.raises(ValueError, match="lifecycle"):
        plan_account_sync(ACCOUNT_ID, **_state(tmp_path, lifecycle=lifecycle))


def test_unknown_unbound_missing_profile_and_bad_health_rejected(tmp_path):
    paths = _state(tmp_path / "one")
    with pytest.raises(ValueError, match="Unknown"):
        plan_account_sync("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", **paths)
    with pytest.raises(ValueError, match="binding"):
        plan_account_sync(ACCOUNT_ID, **_state(tmp_path / "two", bound=False))
    with pytest.raises(ValueError, match="profile"):
        plan_account_sync(ACCOUNT_ID, **_state(tmp_path / "three", profile=False))
    with pytest.raises(ValueError, match="expired"):
        plan_account_sync(ACCOUNT_ID, **_state(tmp_path / "four", health=AuthStatus.EXPIRED))


def test_unknown_health_warns_but_can_preview(tmp_path):
    plan = plan_account_sync(ACCOUNT_ID, **_state(tmp_path, health=None))
    assert plan.warning and "unknown" in plan.warning.lower()
