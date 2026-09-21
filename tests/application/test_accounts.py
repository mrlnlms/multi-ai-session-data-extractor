from src.account_catalog import LifecycleStatus
from src.accounts import AccountEvidence, AccountState
from pathlib import Path
from src.application.accounts import account_actions, add_account_action, auth_check_action, auth_confirm_action, sync_action
from src.workflows.account_sync import AccountSyncPlan

def _account(status):
    return AccountState("Qwen", "work", None, AccountEvidence(), "unknown", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", status)

def test_view_models_expose_all_actions_and_preservation_copy():
    actions = account_actions(_account(LifecycleStatus.ACTIVE))
    assert {item.action for item in actions} == {"lifecycle", "bind", "auth-check", "auth-confirm", "sync", "login"}
    assert all("preserved data will not be deleted" in item.confirmation for item in actions)
    assert "src.platforms.qwen.commands.login --account work" in actions[-1].command

def test_inactive_accounts_expose_no_enabled_sync():
    for status in (LifecycleStatus.DISABLED, LifecycleStatus.HISTORICAL):
        actions = {item.action: item for item in account_actions(_account(status))}
        assert not actions["sync"].enabled and not actions["auth-check"].enabled

def test_add_account_requires_confirmation_to_write(tmp_path):
    path = tmp_path / "catalog.json"
    assert add_account_action(platform="Qwen", display_name="Work", confirmed=False, catalog_path=path).ok
    assert not path.exists()
    assert add_account_action(platform="Qwen", display_name="Work", confirmed=True, catalog_path=path).ok
    assert path.exists()

def test_auth_and_sync_actions_are_confirmation_gated(monkeypatch, tmp_path):
    assert auth_check_action("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", confirmed=False).ok
    plan = AccountSyncPlan("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "Qwen", ())
    monkeypatch.setattr("src.application.accounts.plan_account_sync", lambda *a, **k: plan)
    calls = []
    assert sync_action("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", confirmed=False).ok
    assert sync_action("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", confirmed=True,
                       runner=lambda plan: (calls.append(plan) or (0, "ok")),
                       health_path=tmp_path / "health.json").ok
    assert len(calls) == 1


def test_manual_auth_confirmation_is_confirmation_gated(tmp_path):
    path = tmp_path / "health.json"
    assert auth_confirm_action("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", confirmed=False, health_path=path).ok
    assert not path.exists()


def test_login_command_uses_the_observed_profile_key():
    account = AccountState("ChatGPT", "2", None, AccountEvidence(profile_path=Path(".storage/chatgpt-profile-account-2")),
                           "valid", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", LifecycleStatus.ACTIVE)
    login = next(action for action in account_actions(account) if action.action == "login")
    assert login.command.endswith("--profile account-2")
