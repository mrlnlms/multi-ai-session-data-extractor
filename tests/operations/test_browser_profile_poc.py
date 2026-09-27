from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.account_catalog import (
    AccountCatalog, AccountCatalogRecord, LifecycleStatus, serialize_account_catalog,
)
from src.browser_profile_catalog import (
    BrowserProfileCatalog, write_browser_profile_catalog_atomic,
)
from src.browser_profile_service import assign_account, create_browser_profile
from src.local_browser_profiles import (
    LocalBrowserProfiles, set_local_browser_profile, write_local_browser_profiles_atomic,
)
from src.operations import browser_profile_poc


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)
PROFILE_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
ACCOUNT_IDS = (
    "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb",
    "cccccccc-cccc-4ccc-cccc-cccccccccccc",
    "dddddddd-dddd-4ddd-dddd-dddddddddddd",
)


def test_sample_resolves_three_account_uuids_to_one_existing_directory(monkeypatch, tmp_path: Path):
    storage = tmp_path / ".storage"
    physical = storage / "browser-profile-poc-shared"
    physical.mkdir(parents=True)
    (physical / "Cookies").write_bytes(b"existing-session")
    accounts = AccountCatalog(records=tuple(
        AccountCatalogRecord(account_id, platform, "Foton", None, LifecycleStatus.ACTIVE, NOW, NOW)
        for account_id, platform in zip(ACCOUNT_IDS, ("ChatGPT", "Gemini", "NotebookLM"))
    ))
    accounts_path = tmp_path / "catalog.json"
    accounts_path.write_text(serialize_account_catalog(accounts), encoding="utf-8")
    groups, profile_id = create_browser_profile(
        BrowserProfileCatalog(), display_name="Foton PoC", email=None,
        now=NOW, profile_id_factory=lambda: PROFILE_ID,
    )
    for account_id in ACCOUNT_IDS:
        groups = assign_account(groups, accounts, profile_id=profile_id,
                                account_id=account_id, now=NOW)
    groups_path = tmp_path / "browser_profiles.json"
    write_browser_profile_catalog_atomic(groups_path, groups, expected_before=BrowserProfileCatalog())
    local = set_local_browser_profile(
        LocalBrowserProfiles(), groups, profile_id=profile_id, channel="chromium",
        directory="browser-profile-poc-shared", adopt_existing=True, storage_root=storage,
    )
    local_path = tmp_path / "browser-profile-config.json"
    write_local_browser_profiles_atomic(local_path, local, expected_before=LocalBrowserProfiles())
    observed = []

    async def fake_sample(target, storage_root):
        observed.append((target.path, storage_root))

    monkeypatch.setattr(browser_profile_poc, "_sample", fake_sample)
    args = ["sample", "--profile-id", profile_id, "--verify-account-map",
            "--accounts-path", str(accounts_path), "--groups-path", str(groups_path),
            "--local-path", str(local_path), "--storage-root", str(storage)]
    browser_profile_poc.main(args)
    assert observed == [(physical, storage)]
    assert (physical / "Cookies").read_bytes() == b"existing-session"

    missing_notebook = AccountCatalog(records=accounts.records[:2])
    accounts_path.write_text(serialize_account_catalog(missing_notebook), encoding="utf-8")
    with pytest.raises(ValueError, match="Expected one NotebookLM"):
        browser_profile_poc.main(args)
