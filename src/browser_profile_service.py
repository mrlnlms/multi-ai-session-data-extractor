"""UI-neutral changes to durable browser-profile grouping."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from src.account_catalog import AccountCatalog
from src.browser_profile_catalog import (
    BrowserProfileCatalog, BrowserProfileGroup, canonical_uuid,
)


def _aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def create_browser_profile(
    catalog: BrowserProfileCatalog, *, display_name: str, email: str | None,
    now: datetime, profile_id_factory: Callable[[], UUID] = uuid.uuid4,
) -> tuple[BrowserProfileCatalog, str]:
    _aware(now)
    if not isinstance(display_name, str) or not display_name or display_name != display_name.strip():
        raise ValueError("display_name must be a non-empty trimmed string")
    if email is not None and (not isinstance(email, str) or not email or email != email.strip()):
        raise ValueError("email must be a non-empty trimmed string or None")
    generated = profile_id_factory()
    if not isinstance(generated, UUID):
        raise ValueError("profile_id_factory must return a UUID")
    profile_id = str(generated)
    if catalog.get(profile_id) is not None:
        raise ValueError(f"Duplicate browser profile: {profile_id}")
    record = BrowserProfileGroup(profile_id, display_name, email, (), now, now)
    return BrowserProfileCatalog(records=(*catalog.records, record)), profile_id


def assign_account(
    catalog: BrowserProfileCatalog, accounts: AccountCatalog, *,
    profile_id: str, account_id: str, now: datetime,
) -> BrowserProfileCatalog:
    _aware(now)
    canonical_uuid(profile_id, "profile_id")
    canonical_uuid(account_id, "account_id")
    group = catalog.get(profile_id)
    if group is None:
        raise ValueError(f"Unknown browser profile: {profile_id}")
    account = next((item for item in accounts.records if item.account_id == account_id), None)
    if account is None:
        raise ValueError(f"Unknown account_id: {account_id}")
    if any(account_id in item.account_ids for item in catalog.records):
        raise ValueError(f"Account already assigned to a browser profile: {account_id}")
    account_by_id = {item.account_id: item for item in accounts.records}
    missing_members = [item for item in group.account_ids if item not in account_by_id]
    if missing_members:
        raise ValueError(f"Browser profile has unresolved account IDs: {missing_members}")
    existing_platforms = {
        account_by_id[item].platform for item in group.account_ids
    }
    if account.platform in existing_platforms:
        raise ValueError(f"Browser profile already contains a {account.platform} account")
    if now < group.updated_at:
        raise ValueError("Browser-profile timestamp cannot move backward")
    replacement = replace(group, account_ids=(*group.account_ids, account_id), updated_at=now)
    return BrowserProfileCatalog(records=tuple(
        replacement if item.profile_id == profile_id else item for item in catalog.records
    ))


def unassign_account(
    catalog: BrowserProfileCatalog, *, profile_id: str, account_id: str, now: datetime,
) -> BrowserProfileCatalog:
    _aware(now)
    canonical_uuid(profile_id, "profile_id")
    canonical_uuid(account_id, "account_id")
    group = catalog.get(profile_id)
    if group is None or account_id not in group.account_ids:
        raise ValueError("Account is not assigned to this browser profile")
    if now < group.updated_at:
        raise ValueError("Browser-profile timestamp cannot move backward")
    replacement = replace(
        group, account_ids=tuple(item for item in group.account_ids if item != account_id),
        updated_at=now,
    )
    return BrowserProfileCatalog(records=tuple(
        replacement if item.profile_id == profile_id else item for item in catalog.records
    ))
