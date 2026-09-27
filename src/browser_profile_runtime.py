"""Resolve and exclusively open a machine-local shared browser profile."""

from __future__ import annotations

import fcntl
import hashlib
import os
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from playwright.async_api import BrowserContext, Playwright

from src.account_bindings import DEFAULT_BINDINGS_PATH, load_account_bindings
from src.account_catalog import AccountCatalog, LifecycleStatus, load_account_catalog
from src.accounts import ACCOUNT_ID_ENV
from src.browser_profile_catalog import (
    DEFAULT_CATALOG_PATH, BrowserProfileCatalog, canonical_uuid, load_browser_profile_catalog,
)
from src.local_browser_profiles import (
    DEFAULT_LOCAL_PATH, BrowserChannel, LocalBrowserProfiles, browser_profile_path,
    load_local_browser_profiles,
)


CHROME_ARGS = ["--disable-blink-features=AutomationControlled"]


@dataclass(frozen=True)
class BrowserProfileTarget:
    profile_id: str
    path: Path
    channel: BrowserChannel


class BrowserProfileBusy(RuntimeError):
    """Another operation has opened this browser profile."""


def resolve_platform_browser_target(
    platform: str, profile_key: str, *, legacy_path: Path,
    legacy_channel: BrowserChannel = "chromium",
    accounts_path: Path = Path("data/accounts/catalog.json"),
    bindings_path: Path = DEFAULT_BINDINGS_PATH,
    groups_path: Path = DEFAULT_CATALOG_PATH,
    local_path: Path = DEFAULT_LOCAL_PATH,
    storage_root: Path = Path(".storage"),
) -> BrowserProfileTarget:
    """Resolve a platform command's browser without changing its account identity.

    Unassigned accounts keep their existing directory. An assigned account must
    have a usable local group binding; it never silently falls back to an old
    profile after migration.
    """
    accounts = load_account_catalog(accounts_path)
    bindings = load_account_bindings(bindings_path)
    matches = [record for record in accounts.records
               if record.platform == platform
               and (binding := bindings.get(record.account_id)) is not None
               and binding.profile_key == profile_key]
    runtime_id = os.environ.get(ACCOUNT_ID_ENV)
    if runtime_id:
        canonical_uuid(runtime_id, ACCOUNT_ID_ENV)
        matches = [record for record in matches if record.account_id == runtime_id]
        if not matches:
            raise ValueError(f"{ACCOUNT_ID_ENV} does not match {platform}:{profile_key}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous account binding for {platform}:{profile_key}")
    if not matches:
        return BrowserProfileTarget("", legacy_path, legacy_channel)
    account = matches[0]
    groups = load_browser_profile_catalog(groups_path)
    if not any(account.account_id in group.account_ids for group in groups.records):
        return BrowserProfileTarget("", legacy_path, legacy_channel)
    if account.lifecycle_status is not LifecycleStatus.ACTIVE:
        raise ValueError(f"Inactive account cannot open a browser group: {account.account_id}")
    return resolve_account_browser_profile(
        accounts, groups, load_local_browser_profiles(local_path),
        account_id=account.account_id, storage_root=storage_root,
    )


def resolve_browser_profile(
    catalog: BrowserProfileCatalog, local: LocalBrowserProfiles, *,
    profile_id: str, storage_root: Path,
) -> BrowserProfileTarget:
    canonical_uuid(profile_id, "profile_id")
    if catalog.get(profile_id) is None:
        raise ValueError(f"Unknown browser profile: {profile_id}")
    config = local.get(profile_id)
    if config is None:
        raise ValueError(f"Browser profile has no local configuration: {profile_id}")
    path = browser_profile_path(storage_root, profile_id, local)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Browser-profile directory is missing or invalid: {path}")
    return BrowserProfileTarget(profile_id, path, config.channel)


def resolve_account_browser_profile(
    accounts: AccountCatalog, catalog: BrowserProfileCatalog,
    local: LocalBrowserProfiles, *, account_id: str, storage_root: Path,
) -> BrowserProfileTarget:
    """Follow account UUID -> durable group -> machine-local browser directory."""
    canonical_uuid(account_id, "account_id")
    if not any(item.account_id == account_id for item in accounts.records):
        raise ValueError(f"Unknown account_id: {account_id}")
    groups = [item for item in catalog.records if account_id in item.account_ids]
    if len(groups) != 1:
        raise ValueError(f"Account must belong to exactly one browser group: {account_id}")
    return resolve_browser_profile(
        catalog, local, profile_id=groups[0].profile_id, storage_root=storage_root,
    )


@contextmanager
def browser_profile_lock(storage_root: Path, profile_path: Path) -> Iterator[None]:
    resolved = profile_path.resolve()
    if not resolved.is_relative_to(storage_root.resolve()):
        raise ValueError("Browser-profile directory leaves the local storage root")
    lock_dir = storage_root / "browser-profile-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_key = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    lock_path = lock_dir / f"{lock_key}.lock"
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BrowserProfileBusy("Browser-profile directory is already in use") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


async def launch_persistent_profile(
    playwright: Playwright, user_data_dir: str | Path, **options: Any,
) -> BrowserContext:
    """Open either a legacy path or a locally bound shared browser directory."""
    path = Path(user_data_dir)
    storage_root = Path(".storage")
    local = load_local_browser_profiles()
    shared = next((record for record in local.records
                   if browser_profile_path(storage_root, record.profile_id, local).resolve()
                   == path.resolve()), None)
    if shared is None:
        return await playwright.chromium.launch_persistent_context(str(path), **options)
    options.pop("channel", None)
    if shared.channel == "chrome":
        options["channel"] = "chrome"
    stack = ExitStack()
    stack.enter_context(browser_profile_lock(storage_root, path))
    try:
        context = await playwright.chromium.launch_persistent_context(str(path), **options)
        context.on("close", lambda *_: stack.close())
        return context
    except BaseException:
        stack.close()
        raise


@asynccontextmanager
async def open_browser_profile(
    playwright: Playwright, target: BrowserProfileTarget, *,
    storage_root: Path, headless: bool,
) -> AsyncIterator[BrowserContext]:
    if not target.path.is_dir():
        raise ValueError(f"Browser-profile directory is missing: {target.path}")
    if target.channel not in {"chromium", "chrome"}:
        raise ValueError(f"Unsupported browser channel: {target.channel!r}")
    with browser_profile_lock(storage_root, target.path):
        options = {"channel": "chrome"} if target.channel == "chrome" else {}
        context = await playwright.chromium.launch_persistent_context(
            str(target.path), headless=headless, args=CHROME_ARGS, **options,
        )
        try:
            yield context
        finally:
            await context.close()
