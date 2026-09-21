"""Durable, UI-neutral identity and lifecycle catalog for accounts."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from src.platforms.registry import PLATFORM_ACCOUNT_METADATA


CATALOG_VERSION = 2
LEGACY_CATALOG_VERSION = 1
LEGACY_ACCOUNT_NAMESPACE = uuid.UUID("87ebca56-7875-5f47-9071-5d9db7508442")
_ROOT_FIELDS = frozenset({"version", "accounts"})
_RECORD_FIELDS = frozenset({
    "account_id",
    "platform",
    "display_name",
    "email",
    "lifecycle_status",
    "created_at",
    "updated_at",
})
_LEGACY_RECORD_FIELDS = frozenset({
    "account_id",
    "platform",
    "technical_key",
    "lifecycle_status",
    "created_at",
    "updated_at",
})
_SAFE_TECHNICAL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    HISTORICAL = "historical"


@dataclass(frozen=True)
class AccountCatalogRecord:
    account_id: str
    platform: str
    display_name: str | None
    email: str | None
    lifecycle_status: LifecycleStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AccountCatalog:
    version: int = CATALOG_VERSION
    records: tuple[AccountCatalogRecord, ...] = ()
    # Version-1 locators exist only long enough to migrate legacy paths. They
    # are never serialized into the canonical version-2 catalog.
    legacy_technical_keys: tuple[tuple[str, str], ...] = ()

    @property
    def requires_identity_migration(self) -> bool:
        return bool(self.legacy_technical_keys)

    def legacy_technical_key(self, account_id: str) -> str | None:
        return dict(self.legacy_technical_keys).get(account_id)


def validate_technical_key(value: object, *, allow_archive: bool = True) -> str:
    """Return a safe relative technical key or raise ``ValueError``."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("technical_key must be a non-empty safe string")
    if value.startswith("archive:"):
        archive_key = value.removeprefix("archive:")
        if allow_archive and archive_key and _SAFE_TECHNICAL_KEY.fullmatch(archive_key):
            return value
        raise ValueError("archive technical keys are not capturable")
    if value in {".", ".."} or not _SAFE_TECHNICAL_KEY.fullmatch(value):
        raise ValueError(f"technical_key is unsafe: {value!r}")
    return value


def legacy_account_id(platform: str, technical_key: str) -> str:
    """Return a stable UUID for a technical account predating the catalog."""
    return str(uuid.uuid5(LEGACY_ACCOUNT_NAMESPACE, f"{platform}\0{technical_key}"))


def legacy_fallback_key(platform: str, account_id: str) -> str | None:
    """Recover only fixed pre-catalog namespaces needed to preserve row IDs."""
    metadata = PLATFORM_ACCOUNT_METADATA.get(platform)
    if metadata is None:
        return None
    return next(
        (key for key in metadata.fallback_keys
         if legacy_account_id(platform, key) == account_id),
        None,
    )


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Catalog {field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
    except ValueError as exc:
        raise ValueError(f"Catalog {field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Catalog {field} must be timezone-aware")
    return parsed


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value != value.strip():
        raise ValueError(f"Catalog {field} must be null or a trimmed string")
    return value or None


def _parse_record(value: object, *, legacy: bool) -> tuple[AccountCatalogRecord, str | None]:
    expected_fields = _LEGACY_RECORD_FIELDS if legacy else _RECORD_FIELDS
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        version = LEGACY_CATALOG_VERSION if legacy else CATALOG_VERSION
        raise ValueError(f"Catalog account fields must match version {version} exactly")

    account_id = value["account_id"]
    if not isinstance(account_id, str):
        raise ValueError("Catalog account_id must be a UUID string")
    try:
        uuid.UUID(account_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Catalog account_id must be a valid UUID") from exc

    platform = value["platform"]
    if not isinstance(platform, str) or platform not in PLATFORM_ACCOUNT_METADATA:
        raise ValueError(f"Catalog platform is not supported: {platform!r}")

    technical_key = None
    if legacy:
        try:
            technical_key = validate_technical_key(value["technical_key"], allow_archive=True)
        except ValueError as exc:
            raise ValueError("Catalog technical_key must be a safe relative string") from exc

    lifecycle_value = value["lifecycle_status"]
    try:
        lifecycle_status = LifecycleStatus(lifecycle_value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Catalog lifecycle_status is invalid: {lifecycle_value!r}") from exc

    return AccountCatalogRecord(
        account_id=account_id,
        platform=platform,
        display_name=None if legacy else _optional_text(value["display_name"], "display_name"),
        email=None if legacy else _optional_text(value["email"], "email"),
        lifecycle_status=lifecycle_status,
        created_at=_parse_timestamp(value["created_at"], "created_at"),
        updated_at=_parse_timestamp(value["updated_at"], "updated_at"),
    ), technical_key


def load_account_catalog(path: Path) -> AccountCatalog:
    """Load and strictly validate a versioned catalog; missing is empty."""
    if not path.exists():
        return AccountCatalog()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid account catalog JSON: {path}") from exc

    if not isinstance(raw, Mapping) or set(raw) != _ROOT_FIELDS:
        raise ValueError("Account catalog root fields must be version and accounts")
    if type(raw["version"]) is not int or raw["version"] not in {
        LEGACY_CATALOG_VERSION, CATALOG_VERSION,
    }:
        raise ValueError(f"Unsupported account catalog version: {raw['version']!r}")
    if not isinstance(raw["accounts"], list):
        raise ValueError("Account catalog accounts must be an array")

    legacy = raw["version"] == LEGACY_CATALOG_VERSION
    parsed = tuple(_parse_record(value, legacy=legacy) for value in raw["accounts"])
    records = tuple(record for record, _ in parsed)
    legacy_keys = tuple(
        (record.account_id, technical_key)
        for record, technical_key in parsed
        if technical_key is not None
    )
    account_ids: set[str] = set()
    legacy_identities: set[tuple[str, str]] = set()
    for record in records:
        if record.account_id in account_ids:
            raise ValueError(f"Duplicate account_id: {record.account_id}")
        technical_key = dict(legacy_keys).get(record.account_id)
        identity = (record.platform, technical_key) if technical_key is not None else None
        if identity is not None and identity in legacy_identities:
            raise ValueError(f"Duplicate legacy account identity: {record.platform}:{technical_key}")
        account_ids.add(record.account_id)
        if identity is not None:
            legacy_identities.add(identity)
    return AccountCatalog(
        version=CATALOG_VERSION,
        records=records,
        legacy_technical_keys=legacy_keys,
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Catalog timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def serialize_account_catalog(catalog: AccountCatalog) -> str:
    """Serialize the durable catalog deterministically and without local metadata."""
    payload = {
        "version": catalog.version,
        "accounts": [
            {
                "account_id": record.account_id,
                "platform": record.platform,
                "display_name": record.display_name,
                "email": record.email,
                "lifecycle_status": record.lifecycle_status.value,
                "created_at": _timestamp(record.created_at),
                "updated_at": _timestamp(record.updated_at),
            }
            for record in catalog.records
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def write_account_catalog_atomic(
    path: Path,
    catalog: AccountCatalog,
    *,
    expected_before: AccountCatalog,
) -> None:
    """Replace a catalog only when its current semantic state is expected."""
    current = load_account_catalog(path)
    if current != expected_before:
        raise ValueError(f"Refusing stale account catalog write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(serialize_account_catalog(catalog), encoding="utf-8")
        # Re-read immediately before replacement to catch a concurrent writer.
        if load_account_catalog(path) != expected_before:
            raise ValueError(f"Refusing stale account catalog write: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
