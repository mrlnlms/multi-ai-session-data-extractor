"""UI-neutral presentation and explicit actions for browser-profile groups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from src.account_catalog import load_account_catalog
from src.browser_profile_catalog import (
    DEFAULT_CATALOG_PATH, load_browser_profile_catalog, write_browser_profile_catalog_atomic,
)
from src.browser_profile_service import assign_account, create_browser_profile
from src.local_browser_profiles import (
    DEFAULT_LOCAL_PATH, browser_profile_path, load_local_browser_profiles,
    set_local_browser_profile, write_local_browser_profiles_atomic,
)


@dataclass(frozen=True)
class BrowserProfileOutcome:
    ok: bool
    message: str


def browser_profile_rows(
    *, groups_path: Path = DEFAULT_CATALOG_PATH,
    accounts_path: Path = Path("data/accounts/catalog.json"),
    local_path: Path = DEFAULT_LOCAL_PATH,
    storage_root: Path = Path(".storage"),
) -> list[dict[str, object]]:
    groups = load_browser_profile_catalog(groups_path)
    accounts = load_account_catalog(accounts_path)
    local = load_local_browser_profiles(local_path)
    account_by_id = {item.account_id: item for item in accounts.records}
    rows = []
    for group in groups.records:
        labels = []
        for account_id in group.account_ids:
            account = account_by_id.get(account_id)
            labels.append(f"{account.platform}: {account.display_name or account_id}" if account
                          else f"Missing catalog record: {account_id}")
        config = local.get(group.profile_id)
        path = browser_profile_path(storage_root, group.profile_id, local)
        rows.append({
            "Profile ID": group.profile_id,
            "Name": group.display_name,
            "E-mail": group.email or "—",
            "Accounts": ", ".join(labels) or "—",
            "Local profile": "Present" if path.is_dir() else "Missing",
            "Browser": config.channel if config else "—",
        })
    return rows


def create_browser_profile_action(
    *, profile_id: str, display_name: str, email: str | None,
    confirmed: bool, groups_path: Path = DEFAULT_CATALOG_PATH,
) -> BrowserProfileOutcome:
    try:
        before = load_browser_profile_catalog(groups_path)
        after, _ = create_browser_profile(
            before, display_name=display_name, email=email,
            now=datetime.now(timezone.utc), profile_id_factory=lambda: UUID(profile_id),
        )
        if confirmed:
            write_browser_profile_catalog_atomic(groups_path, after, expected_before=before)
        return BrowserProfileOutcome(True, "Browser profile created." if confirmed else "Preview ready.")
    except ValueError as exc:
        return BrowserProfileOutcome(False, str(exc))


def assign_browser_profile_action(
    *, profile_id: str, account_id: str, confirmed: bool,
    groups_path: Path = DEFAULT_CATALOG_PATH,
    accounts_path: Path = Path("data/accounts/catalog.json"),
) -> BrowserProfileOutcome:
    try:
        before = load_browser_profile_catalog(groups_path)
        after = assign_account(
            before, load_account_catalog(accounts_path), profile_id=profile_id,
            account_id=account_id, now=datetime.now(timezone.utc),
        )
        if confirmed:
            write_browser_profile_catalog_atomic(groups_path, after, expected_before=before)
        return BrowserProfileOutcome(True, "Account associated." if confirmed else "Preview ready.")
    except ValueError as exc:
        return BrowserProfileOutcome(False, str(exc))


def initialize_browser_profile_action(
    *, profile_id: str, channel: str, confirmed: bool,
    groups_path: Path = DEFAULT_CATALOG_PATH,
    local_path: Path = DEFAULT_LOCAL_PATH,
    storage_root: Path = Path(".storage"),
) -> BrowserProfileOutcome:
    try:
        before = load_local_browser_profiles(local_path)
        after = set_local_browser_profile(
            before, load_browser_profile_catalog(groups_path), profile_id=profile_id,
            channel=channel, storage_root=storage_root,
        )
        if confirmed:
            browser_profile_path(storage_root, profile_id, after).mkdir(parents=True, exist_ok=True)
            write_local_browser_profiles_atomic(local_path, after, expected_before=before)
        return BrowserProfileOutcome(True, "Local directory created; login still required." if confirmed
                                     else "Preview ready; no login will be performed.")
    except ValueError as exc:
        return BrowserProfileOutcome(False, str(exc))
