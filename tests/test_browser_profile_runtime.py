import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.browser_profile_catalog import BrowserProfileCatalog
from src.browser_profile_runtime import (
    BrowserProfileBusy, browser_profile_lock, launch_persistent_profile,
    open_browser_profile, resolve_account_browser_profile, resolve_browser_profile,
    resolve_platform_browser_target,
)
from src.browser_profile_service import create_browser_profile
from src.account_catalog import AccountCatalog, AccountCatalogRecord, LifecycleStatus
from src.browser_profile_service import assign_account, unassign_account
from src.local_browser_profiles import LocalBrowserProfiles, set_local_browser_profile
from src.account_bindings import AccountBinding, AccountBindings, write_account_bindings_atomic
from src.account_catalog import write_account_catalog_atomic
from src.browser_profile_catalog import write_browser_profile_catalog_atomic
from src.local_browser_profiles import write_local_browser_profiles_atomic


PROFILE_ID = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _bound_existing(tmp_path: Path):
    storage = tmp_path / ".storage"
    physical = storage / "browser-profile-poc-shared"
    physical.mkdir(parents=True)
    (physical / "Cookies").write_bytes(b"existing-session")
    catalog, _ = create_browser_profile(
        BrowserProfileCatalog(), display_name="Foton", email=None, now=NOW,
        profile_id_factory=lambda: UUID(PROFILE_ID),
    )
    local = set_local_browser_profile(
        LocalBrowserProfiles(), catalog, profile_id=PROFILE_ID, channel="chromium",
        directory="browser-profile-poc-shared", adopt_existing=True, storage_root=storage,
    )
    return catalog, local, storage, physical


def test_resolve_existing_profile_without_copy_and_lock_is_exclusive(tmp_path: Path):
    catalog, local, storage, physical = _bound_existing(tmp_path)
    target = resolve_browser_profile(catalog, local, profile_id=PROFILE_ID, storage_root=storage)
    assert target.path.resolve() == physical.resolve()
    assert target.channel == "chromium"

    with browser_profile_lock(storage, physical):
        with pytest.raises(BrowserProfileBusy, match="already in use"):
            with browser_profile_lock(storage, physical):
                pass
    with browser_profile_lock(storage, physical):
        pass
    assert (physical / "Cookies").read_bytes() == b"existing-session"


def test_account_uuid_resolves_through_durable_group_to_local_directory(tmp_path: Path):
    unassigned, local, storage, physical = _bound_existing(tmp_path)
    account_id = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
    accounts = AccountCatalog(records=(AccountCatalogRecord(
        account_id, "Gemini", "Foton", None, LifecycleStatus.ACTIVE, NOW, NOW,
    ),))
    catalog = assign_account(
        unassigned, accounts, profile_id=PROFILE_ID, account_id=account_id, now=NOW,
    )
    target = resolve_account_browser_profile(
        accounts, catalog, local, account_id=account_id, storage_root=storage,
    )
    assert target.path == physical
    with pytest.raises(ValueError, match="exactly one"):
        resolve_account_browser_profile(
            accounts, unassigned, local,
            account_id=account_id, storage_root=storage,
        )


def test_lock_blocks_a_second_process_for_the_same_directory(tmp_path: Path):
    _, _, storage, physical = _bound_existing(tmp_path)
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from src.browser_profile_runtime import browser_profile_lock, BrowserProfileBusy\n"
        "try:\n"
        "    with browser_profile_lock(Path(sys.argv[1]), Path(sys.argv[2])): pass\n"
        "except BrowserProfileBusy:\n"
        "    raise SystemExit(7)\n"
    )
    command = [sys.executable, "-c", script, str(storage), str(physical)]
    with browser_profile_lock(storage, physical):
        assert subprocess.run(command, capture_output=True, check=False).returncode == 7
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0


@pytest.mark.asyncio
async def test_open_browser_profile_uses_locked_channel_and_closes(tmp_path: Path):
    catalog, local, storage, _ = _bound_existing(tmp_path)
    target = resolve_browser_profile(catalog, local, profile_id=PROFILE_ID, storage_root=storage)
    calls = []

    class FakeContext:
        async def close(self):
            calls.append("close")

    class FakeChromium:
        async def launch_persistent_context(self, path, **kwargs):
            calls.append((path, kwargs))
            return FakeContext()

    playwright = SimpleNamespace(chromium=FakeChromium())
    async with open_browser_profile(playwright, target, storage_root=storage, headless=True):
        with pytest.raises(BrowserProfileBusy):
            with browser_profile_lock(storage, target.path):
                pass

    assert calls[0][0] == str(target.path)
    assert calls[0][1]["headless"] is True
    assert "channel" not in calls[0][1]
    assert calls[1] == "close"
    with browser_profile_lock(storage, target.path):
        pass


def test_platform_key_selects_shared_directory_without_changing_account_binding(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    catalog, local, storage, physical = _bound_existing(tmp_path)
    account_id = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
    accounts = AccountCatalog(records=(AccountCatalogRecord(
        account_id, "Gemini", "Personal", None, LifecycleStatus.ACTIVE, NOW, NOW,
    ),))
    (tmp_path / "data" / "accounts").mkdir(parents=True)
    write_account_catalog_atomic(
        tmp_path / "data" / "accounts" / "catalog.json", accounts,
        expected_before=AccountCatalog(),
    )
    bindings = AccountBindings(records=(AccountBinding(account_id, "2", NOW),))
    write_account_bindings_atomic(
        storage / "account-bindings.json", bindings, expected_before=AccountBindings(),
    )
    assigned = assign_account(catalog, accounts, profile_id=PROFILE_ID, account_id=account_id, now=NOW)
    write_browser_profile_catalog_atomic(
        tmp_path / "data" / "accounts" / "browser_profiles.json", assigned,
        expected_before=BrowserProfileCatalog(),
    )
    write_local_browser_profiles_atomic(
        storage / "browser-profile-config.json", local, expected_before=LocalBrowserProfiles(),
    )

    target = resolve_platform_browser_target(
        "Gemini", "2", legacy_path=storage / "gemini-profile-2",
    )
    assert target.path.resolve() == physical.resolve()
    assert target.channel == "chromium"
    assert resolve_platform_browser_target(
        "Gemini", "unknown", legacy_path=storage / "gemini-profile-unknown",
    ).path == storage / "gemini-profile-unknown"
    (storage / "browser-profile-config.json").unlink()
    with pytest.raises(ValueError, match="no local configuration"):
        resolve_platform_browser_target("Gemini", "2", legacy_path=storage / "gemini-profile-2")
    unassigned = unassign_account(
        assigned, profile_id=PROFILE_ID, account_id=account_id, now=NOW,
    )
    write_browser_profile_catalog_atomic(
        tmp_path / "data" / "accounts" / "browser_profiles.json", unassigned,
        expected_before=assigned,
    )
    assert resolve_platform_browser_target(
        "Gemini", "2", legacy_path=storage / "gemini-profile-2",
    ).path == storage / "gemini-profile-2"


@pytest.mark.asyncio
async def test_shared_launch_uses_local_channel_and_holds_directory_lock(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    catalog, _, storage, physical = _bound_existing(tmp_path)
    local = set_local_browser_profile(
        LocalBrowserProfiles(), catalog, profile_id=PROFILE_ID, channel="chrome",
        directory="browser-profile-poc-shared", adopt_existing=True, storage_root=storage,
    )
    write_local_browser_profiles_atomic(
        storage / "browser-profile-config.json", local, expected_before=LocalBrowserProfiles(),
    )
    calls = []

    class FakeContext:
        def on(self, event, callback):
            assert event == "close"
            self.close_callback = callback

        async def close(self):
            self.close_callback(self)

    class FakeChromium:
        async def launch_persistent_context(self, path, **kwargs):
            calls.append((path, kwargs))
            return FakeContext()

    context = await launch_persistent_profile(
        SimpleNamespace(chromium=FakeChromium()), physical,
        headless=True, channel="chromium",
    )
    assert calls == [(str(physical), {"headless": True, "channel": "chrome"})]
    with pytest.raises(BrowserProfileBusy):
        with browser_profile_lock(storage, physical):
            pass
    await context.close()
    with browser_profile_lock(storage, physical):
        pass
