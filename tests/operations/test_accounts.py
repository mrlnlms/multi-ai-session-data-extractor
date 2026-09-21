from datetime import datetime, timezone

from src.account_catalog import AccountCatalog, AccountCatalogRecord, LifecycleStatus, load_account_catalog, write_account_catalog_atomic
from src.auth_health import AuthEvidenceMethod, AuthStatus, load_auth_health
from src.operations.accounts import main

ACCOUNT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def _args(tmp_path, *command):
    return ["--catalog-path", str(tmp_path / "catalog.json"), "--bindings-path", str(tmp_path / "bindings.json"), "--health-path", str(tmp_path / "health.json"), *command]


def test_create_previews_then_applies_to_injected_catalog(tmp_path, capsys):
    assert main(_args(tmp_path, "create", "--platform", "Qwen", "--display-name", "Work")) == 0
    assert not (tmp_path / "catalog.json").exists()
    assert "preserved data will not be deleted" in capsys.readouterr().out
    assert main(_args(tmp_path, "create", "--platform", "Qwen", "--display-name", "Work", "--apply")) == 0
    assert load_account_catalog(tmp_path / "catalog.json").records[0].display_name == "Work"


def test_lifecycle_and_bind_are_preview_first(tmp_path):
    catalog = AccountCatalog(records=(AccountCatalogRecord(ACCOUNT_ID, "Qwen", None, None, LifecycleStatus.ACTIVE, NOW, NOW),))
    write_account_catalog_atomic(tmp_path / "catalog.json", catalog, expected_before=AccountCatalog())
    assert main(_args(tmp_path, "lifecycle", ACCOUNT_ID, "historical")) == 0
    assert load_account_catalog(tmp_path / "catalog.json").records[0].lifecycle_status is LifecycleStatus.ACTIVE
    assert main(_args(tmp_path, "bind", ACCOUNT_ID, "--profile-key", "work")) == 0
    assert not (tmp_path / "bindings.json").exists()


def test_parser_exposes_no_delete_command():
    from src.operations.accounts import _parser
    choices = _parser()._subparsers._group_actions[0].choices
    assert set(choices) == {"list", "create", "edit", "lifecycle", "bind", "auth-check", "auth-confirm"}


def test_auth_confirm_is_preview_first_and_records_operator_evidence(tmp_path):
    catalog = AccountCatalog(records=(AccountCatalogRecord(ACCOUNT_ID, "Qwen", None, None, LifecycleStatus.ACTIVE, NOW, NOW),))
    write_account_catalog_atomic(tmp_path / "catalog.json", catalog, expected_before=AccountCatalog())
    assert main(_args(tmp_path, "auth-confirm", ACCOUNT_ID)) == 0
    assert not (tmp_path / "health.json").exists()
    assert main(_args(tmp_path, "auth-confirm", ACCOUNT_ID, "--apply")) == 0
    record = load_auth_health(tmp_path / "health.json").get(ACCOUNT_ID)
    assert record.status is AuthStatus.VALID
    assert record.evidence_method is AuthEvidenceMethod.OPERATOR
