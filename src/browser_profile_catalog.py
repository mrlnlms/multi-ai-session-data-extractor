"""Durable browser-profile groups; no browser sessions or local paths live here."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CATALOG_VERSION = 1
DEFAULT_CATALOG_PATH = Path("data/accounts/browser_profiles.json")
_RECORD_FIELDS = frozenset({
    "profile_id", "display_name", "email", "account_ids", "created_at", "updated_at",
})


@dataclass(frozen=True)
class BrowserProfileGroup:
    profile_id: str
    display_name: str
    email: str | None
    account_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BrowserProfileCatalog:
    version: int = CATALOG_VERSION
    records: tuple[BrowserProfileGroup, ...] = ()

    def get(self, profile_id: str) -> BrowserProfileGroup | None:
        return next((item for item in self.records if item.profile_id == profile_id), None)


def canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UUID string")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid UUID") from exc
    if parsed != value:
        raise ValueError(f"{field} must be a canonical UUID")
    return parsed


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    return value


def _validate(catalog: BrowserProfileCatalog) -> None:
    if catalog.version != CATALOG_VERSION:
        raise ValueError(f"Unsupported browser-profile catalog version: {catalog.version!r}")
    profile_ids: set[str] = set()
    assigned_accounts: set[str] = set()
    for record in catalog.records:
        canonical_uuid(record.profile_id, "profile_id")
        _text(record.display_name, "display_name")
        _text(record.email, "email", optional=True)
        if record.profile_id in profile_ids:
            raise ValueError(f"Duplicate browser profile: {record.profile_id}")
        if record.created_at.tzinfo is None or record.updated_at.tzinfo is None:
            raise ValueError("Browser-profile timestamps must be timezone-aware")
        if record.updated_at < record.created_at:
            raise ValueError("Browser-profile updated_at precedes created_at")
        profile_ids.add(record.profile_id)
        for account_id in record.account_ids:
            canonical_uuid(account_id, "account_id")
            if account_id in assigned_accounts:
                raise ValueError(f"Account assigned to more than one browser profile: {account_id}")
            assigned_accounts.add(account_id)


def load_browser_profile_catalog(path: Path = DEFAULT_CATALOG_PATH) -> BrowserProfileCatalog:
    if not path.exists():
        return BrowserProfileCatalog()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid browser-profile catalog JSON: {path}") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"version", "profiles"}:
        raise ValueError("Browser-profile catalog root fields must be version and profiles")
    if type(raw["version"]) is not int or raw["version"] != CATALOG_VERSION:
        raise ValueError(f"Unsupported browser-profile catalog version: {raw['version']!r}")
    if not isinstance(raw["profiles"], list):
        raise ValueError("Browser-profile catalog profiles must be an array")
    records = []
    for item in raw["profiles"]:
        if not isinstance(item, Mapping) or set(item) != _RECORD_FIELDS:
            raise ValueError("Browser-profile fields must match version 1 exactly")
        account_ids = item["account_ids"]
        if not isinstance(account_ids, list):
            raise ValueError("Browser-profile account_ids must be an array")
        records.append(BrowserProfileGroup(
            profile_id=canonical_uuid(item["profile_id"], "profile_id"),
            display_name=_text(item["display_name"], "display_name"),
            email=_text(item["email"], "email", optional=True),
            account_ids=tuple(canonical_uuid(value, "account_id") for value in account_ids),
            created_at=_timestamp(item["created_at"], "created_at"),
            updated_at=_timestamp(item["updated_at"], "updated_at"),
        ))
    catalog = BrowserProfileCatalog(records=tuple(records))
    _validate(catalog)
    return catalog


def serialize_browser_profile_catalog(catalog: BrowserProfileCatalog) -> str:
    _validate(catalog)
    payload = {"version": catalog.version, "profiles": [
        {
            "profile_id": item.profile_id,
            "display_name": item.display_name,
            "email": item.email,
            "account_ids": list(item.account_ids),
            "created_at": item.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "updated_at": item.updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        for item in catalog.records
    ]}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def write_browser_profile_catalog_atomic(
    path: Path, catalog: BrowserProfileCatalog, *, expected_before: BrowserProfileCatalog,
) -> None:
    serialized = serialize_browser_profile_catalog(catalog)
    if load_browser_profile_catalog(path) != expected_before:
        raise ValueError(f"Refusing stale browser-profile catalog write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        if load_browser_profile_catalog(path) != expected_before:
            raise ValueError(f"Refusing stale browser-profile catalog write: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
