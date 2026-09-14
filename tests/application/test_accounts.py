from src.account_catalog import LifecycleStatus
from src.accounts import AccountEvidence, AccountState
from src.application.accounts import account_actions, add_account_action, auth_check_action, sync_action

def _account(status):
    return AccountState("Qwen", "work", None, AccountEvidence(), "unknown", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", status)

def test_view_models_expose_all_actions_and_preservation_copy():
    actions = account_actions(_account(LifecycleStatus.ACTIVE))
    assert {item.action for item in actions} == {"lifecycle", "bind", "auth-check", "sync", "login"}
    assert all("preserved data will not be deleted" in item.confirmation for item in actions)
    assert "src.platforms.qwen.commands.login --account work" in actions[-1].command

def test_inactive_accounts_expose_no_enabled_sync():
    for status in (LifecycleStatus.DISABLED, LifecycleStatus.HISTORICAL):
        actions = {item.action: item for item in account_actions(_account(status))}
        assert not actions["sync"].enabled and not actions["auth-check"].enabled

def test_add_account_requires_confirmation_to_write(tmp_path):
    path = tmp_path / "catalog.json"
    assert add_account_action(platform="Qwen", technical_key="work", confirmed=False, catalog_path=path).ok
    assert not path.exists()
    assert add_account_action(platform="Qwen", technical_key="work", confirmed=True, catalog_path=path).ok
    assert path.exists()

def test_auth_and_sync_actions_are_confirmation_gated(monkeypatch):
    assert auth_check_action("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", confirmed=False).ok
    monkeypatch.setattr("src.application.accounts.plan_account_sync", lambda *a, **k: object())
    calls = []
    assert sync_action("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", confirmed=False).ok
    assert sync_action("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", confirmed=True,
                       runner=lambda plan: (calls.append(plan) or (0, "ok"))).ok
    assert len(calls) == 1
