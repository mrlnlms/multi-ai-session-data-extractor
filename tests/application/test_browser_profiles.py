from datetime import datetime, timezone
from pathlib import Path

from src.account_catalog import AccountCatalog, AccountCatalogRecord, LifecycleStatus, serialize_account_catalog
from src.application.browser_profiles import (
    assign_browser_profile_action, browser_profile_rows, create_browser_profile_action,
    initialize_browser_profile_action,
)
from src.browser_profile_catalog import load_browser_profile_catalog


PROFILE_ID = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
ACCOUNT_ID = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def test_browser_profile_actions_are_preview_first_and_recoverable_without_local_state(tmp_path: Path):
    accounts_path = tmp_path / "data" / "accounts" / "catalog.json"
    accounts_path.parent.mkdir(parents=True)
    accounts = AccountCatalog(records=(AccountCatalogRecord(
        ACCOUNT_ID, "Gemini", "Foton", "owner@example.test",
        LifecycleStatus.ACTIVE, NOW, NOW,
    ),))
    accounts_path.write_text(serialize_account_catalog(accounts), encoding="utf-8")
    groups_path = accounts_path.with_name("browser_profiles.json")
    local_path = tmp_path / ".storage" / "browser-profile-config.json"
    storage_root = tmp_path / ".storage"

    args = dict(profile_id=PROFILE_ID, display_name="Foton", email="owner@example.test",
                groups_path=groups_path)
    assert create_browser_profile_action(**args, confirmed=False).ok
    assert not groups_path.exists()
    assert create_browser_profile_action(**args, confirmed=True).ok
    assert assign_browser_profile_action(
        profile_id=PROFILE_ID, account_id=ACCOUNT_ID, confirmed=False,
        groups_path=groups_path, accounts_path=accounts_path,
    ).ok
    assert load_browser_profile_catalog(groups_path).records[0].account_ids == ()
    assert assign_browser_profile_action(
        profile_id=PROFILE_ID, account_id=ACCOUNT_ID, confirmed=True,
        groups_path=groups_path, accounts_path=accounts_path,
    ).ok

    rows = browser_profile_rows(
        groups_path=groups_path, accounts_path=accounts_path,
        local_path=local_path, storage_root=storage_root,
    )
    assert rows[0]["Accounts"] == "Gemini: Foton"
    assert rows[0]["Local profile"] == "Missing"
    assert rows[0]["Browser"] == "—"
    assert initialize_browser_profile_action(
        profile_id=PROFILE_ID, channel="chromium", confirmed=False,
        groups_path=groups_path, local_path=local_path, storage_root=storage_root,
    ).ok
    assert not local_path.exists()
    assert initialize_browser_profile_action(
        profile_id=PROFILE_ID, channel="chromium", confirmed=True,
        groups_path=groups_path, local_path=local_path, storage_root=storage_root,
    ).ok
    assert browser_profile_rows(
        groups_path=groups_path, accounts_path=accounts_path,
        local_path=local_path, storage_root=storage_root,
    )[0]["Local profile"] == "Present"


def test_browser_profile_rows_preserve_missing_account_reference(tmp_path: Path):
    groups_path = tmp_path / "browser_profiles.json"
    accounts_path = tmp_path / "catalog.json"
    accounts_path.write_text(serialize_account_catalog(AccountCatalog(records=(
        AccountCatalogRecord(ACCOUNT_ID, "Gemini", None, None, LifecycleStatus.ACTIVE, NOW, NOW),
    ))), encoding="utf-8")
    assert create_browser_profile_action(
        profile_id=PROFILE_ID, display_name="Foton", email=None,
        confirmed=True, groups_path=groups_path,
    ).ok
    assert assign_browser_profile_action(
        profile_id=PROFILE_ID, account_id=ACCOUNT_ID, confirmed=True,
        groups_path=groups_path, accounts_path=accounts_path,
    ).ok
    accounts_path.unlink()
    assert browser_profile_rows(
        groups_path=groups_path, accounts_path=accounts_path,
        storage_root=tmp_path / ".storage",
    ) == [
        {
            "Profile ID": PROFILE_ID,
            "Name": "Foton",
            "E-mail": "—",
            "Accounts": f"Missing catalog record: {ACCOUNT_ID}",
            "Local profile": "Missing",
            "Browser": "—",
        }
    ]
