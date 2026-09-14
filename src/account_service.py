"""Immutable domain operations for the durable account catalog."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.account_catalog import (
    AccountCatalog,
    AccountCatalogRecord,
    LifecycleStatus,
    validate_technical_key,
)
from src.platforms.registry import PLATFORM_ACCOUNT_METADATA


@dataclass(frozen=True)
class AccountCatalogChange:
    before: AccountCatalog
    after: AccountCatalog
    account_id: str
    action: str


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def create_account(
    catalog: AccountCatalog,
    *,
    platform: str,
    technical_key: str,
    now: datetime,
    account_id_factory: Callable[[], UUID] = uuid.uuid4,
) -> AccountCatalogChange:
    _aware(now, "now")
    if platform not in PLATFORM_ACCOUNT_METADATA:
        raise ValueError(f"Unsupported account platform: {platform!r}")
    technical_key = validate_technical_key(technical_key, allow_archive=False)
    if any((record.platform, record.technical_key) == (platform, technical_key) for record in catalog.records):
        raise ValueError(f"Duplicate account identity: {platform}:{technical_key}")
    generated = account_id_factory()
    if not isinstance(generated, UUID):
        raise ValueError("account_id_factory must return a UUID")
    account_id = str(generated)
    if any(record.account_id == account_id for record in catalog.records):
        raise ValueError(f"Duplicate account_id: {account_id}")
    record = AccountCatalogRecord(
        account_id=account_id,
        platform=platform,
        technical_key=technical_key,
        lifecycle_status=LifecycleStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    after = AccountCatalog(version=catalog.version, records=(*catalog.records, record))
    return AccountCatalogChange(catalog, after, account_id, "create")


def set_lifecycle(
    catalog: AccountCatalog,
    account_id: str,
    lifecycle_status: LifecycleStatus,
    *,
    now: datetime,
) -> AccountCatalogChange:
    _aware(now, "now")
    try:
        lifecycle_status = LifecycleStatus(lifecycle_status)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid lifecycle status: {lifecycle_status!r}") from exc
    matching = [record for record in catalog.records if record.account_id == account_id]
    if not matching:
        raise ValueError(f"Unknown account_id: {account_id}")
    current = matching[0]
    if current.lifecycle_status is lifecycle_status:
        raise ValueError("Lifecycle transition is a no-op")
    if now < current.created_at or now < current.updated_at:
        raise ValueError("Lifecycle timestamp cannot move backward")
    replacement = AccountCatalogRecord(
        account_id=current.account_id,
        platform=current.platform,
        technical_key=current.technical_key,
        lifecycle_status=lifecycle_status,
        created_at=current.created_at,
        updated_at=now,
    )
    after = AccountCatalog(
        version=catalog.version,
        records=tuple(replacement if record.account_id == account_id else record for record in catalog.records),
    )
    return AccountCatalogChange(catalog, after, account_id, f"lifecycle:{lifecycle_status.value}")
