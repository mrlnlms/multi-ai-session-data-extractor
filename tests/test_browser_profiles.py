import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.account_catalog import AccountCatalog, AccountCatalogRecord, LifecycleStatus, serialize_account_catalog
from src.browser_profile_catalog import (
    BrowserProfileCatalog, load_browser_profile_catalog, serialize_browser_profile_catalog,
    write_browser_profile_catalog_atomic,
)
from src.browser_profile_service import assign_account, create_browser_profile, unassign_account
from src.local_browser_profiles import (
    LocalBrowserProfiles, browser_profile_path, load_local_browser_profiles,
    set_local_browser_profile, write_local_browser_profiles_atomic,
)
from src.operations.browser_profiles import main
from src.operations import browser_profiles as browser_profile_operations
from src.browser_profile_runtime import BrowserProfileTarget


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)
FOTON_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
PERSONAL_ID = UUID("bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb")
CHATGPT_ID = "cccccccc-cccc-4ccc-cccc-cccccccccccc"
GEMINI_ID = "dddddddd-dddd-4ddd-dddd-dddddddddddd"
SECOND_CHATGPT_ID = "eeeeeeee-eeee-4eee-eeee-eeeeeeeeeeee"


def _accounts() -> AccountCatalog:
    return AccountCatalog(records=tuple(
        AccountCatalogRecord(account_id, platform, None, None, LifecycleStatus.ACTIVE, NOW, NOW)
        for account_id, platform in (
            (CHATGPT_ID, "ChatGPT"), (GEMINI_ID, "Gemini"),
            (SECOND_CHATGPT_ID, "ChatGPT"),
        )
    ))


def test_durable_group_roundtrip_keeps_membership_and_excludes_session_state(tmp_path: Path):
    catalog, profile_id = create_browser_profile(
        BrowserProfileCatalog(), display_name="Foton", email="owner@example.test",
        now=NOW, profile_id_factory=lambda: FOTON_ID,
    )
    catalog = assign_account(catalog, _accounts(), profile_id=profile_id, account_id=CHATGPT_ID, now=NOW)
    catalog = assign_account(catalog, _accounts(), profile_id=profile_id, account_id=GEMINI_ID, now=NOW)
    path = tmp_path / "data" / "accounts" / "browser_profiles.json"
    write_browser_profile_catalog_atomic(path, catalog, expected_before=BrowserProfileCatalog())

    assert load_browser_profile_catalog(path) == catalog
    assert catalog.records[0].account_ids == (CHATGPT_ID, GEMINI_ID)
    serialized = serialize_browser_profile_catalog(catalog)
    assert "owner@example.test" in serialized
    assert all(term not in serialized for term in ("cookie", "channel", "profile_path", ".storage"))


def test_group_assignment_rejects_duplicate_membership_and_same_platform():
    catalog, profile_id = create_browser_profile(
        BrowserProfileCatalog(), display_name="Foton", email=None,
        now=NOW, profile_id_factory=lambda: FOTON_ID,
    )
    catalog = assign_account(catalog, _accounts(), profile_id=profile_id, account_id=CHATGPT_ID, now=NOW)
    with pytest.raises(ValueError, match="already assigned"):
        assign_account(catalog, _accounts(), profile_id=profile_id, account_id=CHATGPT_ID, now=NOW)
    with pytest.raises(ValueError, match="already contains a ChatGPT"):
        assign_account(catalog, _accounts(), profile_id=profile_id, account_id=SECOND_CHATGPT_ID, now=NOW)
    assert unassign_account(catalog, profile_id=profile_id, account_id=CHATGPT_ID, now=NOW).records[0].account_ids == ()


def test_durable_catalog_rejects_duplicate_association_and_stale_write(tmp_path: Path):
    catalog, profile_id = create_browser_profile(
        BrowserProfileCatalog(), display_name="Foton", email=None,
        now=NOW, profile_id_factory=lambda: FOTON_ID,
    )
    assigned = assign_account(catalog, _accounts(), profile_id=profile_id, account_id=CHATGPT_ID, now=NOW)
    path = tmp_path / "browser_profiles.json"
    write_browser_profile_catalog_atomic(path, assigned, expected_before=BrowserProfileCatalog())
    with pytest.raises(ValueError, match="stale"):
        write_browser_profile_catalog_atomic(path, catalog, expected_before=BrowserProfileCatalog())
    second, _ = create_browser_profile(
        assigned, display_name="Personal", email=None, now=NOW,
        profile_id_factory=lambda: PERSONAL_ID,
    )
    duplicate = second.records[1].__class__(
        str(PERSONAL_ID), "Personal", None, (CHATGPT_ID,), NOW, NOW,
    )
    with pytest.raises(ValueError, match="more than one"):
        serialize_browser_profile_catalog(BrowserProfileCatalog(records=(assigned.records[0], duplicate)))


def test_local_config_is_separate_and_cannot_switch_existing_profile_channel(tmp_path: Path):
    catalog, profile_id = create_browser_profile(
        BrowserProfileCatalog(), display_name="Foton", email=None,
        now=NOW, profile_id_factory=lambda: FOTON_ID,
    )
    storage = tmp_path / ".storage"
    config = set_local_browser_profile(
        LocalBrowserProfiles(), catalog, profile_id=profile_id,
        channel="chromium", storage_root=storage,
    )
    path = storage / "browser-profile-config.json"
    write_local_browser_profiles_atomic(path, config, expected_before=LocalBrowserProfiles())
    assert load_local_browser_profiles(path) == config
    physical = browser_profile_path(storage, profile_id)
    assert physical == storage / "browser-profiles" / profile_id
    physical.mkdir(parents=True)
    with pytest.raises(ValueError, match="Cannot change"):
        set_local_browser_profile(config, catalog, profile_id=profile_id,
                                  channel="chrome", storage_root=storage)
    (physical / "Cookies").touch()
    with pytest.raises(ValueError, match="no channel record"):
        set_local_browser_profile(LocalBrowserProfiles(), catalog, profile_id=profile_id,
                                  channel="chromium", storage_root=storage)


def test_existing_profile_can_be_bound_without_copying_or_changing_cookies(tmp_path: Path):
    catalog, profile_id = create_browser_profile(
        BrowserProfileCatalog(), display_name="Foton", email=None,
        now=NOW, profile_id_factory=lambda: FOTON_ID,
    )
    storage = tmp_path / ".storage"
    existing = storage / "browser-profile-poc-shared"
    existing.mkdir(parents=True)
    cookie = existing / "Cookies"
    cookie.write_bytes(b"existing-session")
    config = set_local_browser_profile(
        LocalBrowserProfiles(), catalog, profile_id=profile_id, channel="chromium",
        directory="browser-profile-poc-shared", adopt_existing=True, storage_root=storage,
    )

    assert browser_profile_path(storage, profile_id, config) == existing
    assert cookie.read_bytes() == b"existing-session"
    with pytest.raises(ValueError, match="safe relative path"):
        set_local_browser_profile(
            LocalBrowserProfiles(), catalog, profile_id=profile_id, channel="chromium",
            directory="../outside", adopt_existing=True, storage_root=storage,
        )


def test_restore_keeps_grouping_without_local_cookies(tmp_path: Path):
    catalog, profile_id = create_browser_profile(
        BrowserProfileCatalog(), display_name="Foton", email="owner@example.test",
        now=NOW, profile_id_factory=lambda: FOTON_ID,
    )
    catalog = assign_account(catalog, _accounts(), profile_id=profile_id, account_id=GEMINI_ID, now=NOW)
    restored_data = tmp_path / "restored" / "data" / "accounts" / "browser_profiles.json"
    write_browser_profile_catalog_atomic(restored_data, catalog, expected_before=BrowserProfileCatalog())

    assert load_browser_profile_catalog(restored_data).records[0].account_ids == (GEMINI_ID,)
    assert load_local_browser_profiles(tmp_path / "restored" / ".storage" / "browser-profile-config.json") == LocalBrowserProfiles()
    assert not browser_profile_path(tmp_path / "restored" / ".storage", profile_id).exists()


def test_cli_preview_and_apply_keep_foton_out_of_real_catalog(tmp_path: Path, capsys):
    accounts_path = tmp_path / "data" / "accounts" / "catalog.json"
    accounts_path.parent.mkdir(parents=True)
    accounts_path.write_text(serialize_account_catalog(_accounts()), encoding="utf-8")
    groups_path = accounts_path.with_name("browser_profiles.json")
    local_path = tmp_path / ".storage" / "browser-profile-config.json"
    base = ["--groups-path", str(groups_path), "--accounts-path", str(accounts_path),
            "--local-path", str(local_path), "--storage-root", str(tmp_path / ".storage")]
    create = ["create", "--display-name", "Foton", "--email", "owner@example.test",
              "--profile-id", str(FOTON_ID)]

    assert main([*base, *create]) == 0
    assert not groups_path.exists()
    assert main([*base, *create, "--apply"]) == 0
    assert main([*base, "assign", str(FOTON_ID), CHATGPT_ID]) == 0
    assert load_browser_profile_catalog(groups_path).records[0].account_ids == ()
    assert main([*base, "assign", str(FOTON_ID), CHATGPT_ID, "--apply"]) == 0
    assert main([*base, "local-init", str(FOTON_ID), "--apply"]) == 0
    assert browser_profile_path(tmp_path / ".storage", str(FOTON_ID)).is_dir()
    assert load_local_browser_profiles(local_path).records[0].channel == "chromium"
    assert main([*base, "list"]) == 0
    assert "accounts=1  local=present  channel=chromium" in capsys.readouterr().out


def test_cli_binds_existing_local_directory_without_copy(tmp_path: Path, capsys):
    groups_path = tmp_path / "data" / "accounts" / "browser_profiles.json"
    local_path = tmp_path / ".storage" / "browser-profile-config.json"
    storage = tmp_path / ".storage"
    existing = storage / "browser-profile-poc-shared"
    existing.mkdir(parents=True)
    (existing / "Cookies").write_bytes(b"existing-session")
    base = ["--groups-path", str(groups_path), "--local-path", str(local_path),
            "--storage-root", str(storage)]
    assert main([*base, "create", "--display-name", "Foton",
                 "--profile-id", str(FOTON_ID), "--apply"]) == 0
    command = [*base, "local-bind", str(FOTON_ID),
               "--directory", "browser-profile-poc-shared", "--channel", "chromium"]
    assert main(command) == 0
    assert not local_path.exists()
    assert main([*command, "--apply"]) == 0
    assert browser_profile_path(storage, str(FOTON_ID), load_local_browser_profiles(local_path)) == existing
    assert (existing / "Cookies").read_bytes() == b"existing-session"
    assert main([*base, "list"]) == 0
    assert "local=present  channel=chromium" in capsys.readouterr().out


def test_open_site_uses_one_website_and_closes_extra_tabs(tmp_path: Path, monkeypatch):
    calls = []

    class Page:
        def __init__(self, name):
            self.name = name

        async def goto(self, url, **options):
            calls.append((self.name, "goto", url))

        async def close(self):
            calls.append((self.name, "close"))

    first, extra = Page("first"), Page("extra")

    class Context:
        pages = [first, extra]

        async def new_page(self):
            raise AssertionError("An existing page should be reused")

        async def wait_for_event(self, event, **options):
            calls.append(("context", event))

    @asynccontextmanager
    async def fake_playwright():
        yield object()

    @asynccontextmanager
    async def fake_browser(*args, **kwargs):
        yield Context()

    monkeypatch.setattr("playwright.async_api.async_playwright", fake_playwright)
    monkeypatch.setattr(browser_profile_operations, "open_browser_profile", fake_browser)
    monkeypatch.setattr(browser_profile_operations, "load_browser_profile_catalog", lambda path: object())
    monkeypatch.setattr(browser_profile_operations, "load_local_browser_profiles", lambda path: object())
    monkeypatch.setattr(
        browser_profile_operations, "resolve_browser_profile", lambda *args, **kwargs:
        BrowserProfileTarget(str(FOTON_ID), tmp_path, "chrome"),
    )

    asyncio.run(browser_profile_operations._open_site(
        str(FOTON_ID), "https://chatgpt.com/", groups_path=tmp_path / "groups.json",
        local_path=tmp_path / "local.json", storage_root=tmp_path,
    ))

    assert calls == [
        ("extra", "close"),
        ("first", "goto", "https://chatgpt.com/"),
        ("context", "close"),
    ]
