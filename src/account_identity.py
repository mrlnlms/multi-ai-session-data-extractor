"""Resolve immutable account provenance from the durable account catalog."""

from __future__ import annotations

import uuid
from pathlib import Path

from src.account_catalog import load_account_catalog
from src.platforms.registry import PLATFORM_ACCOUNT_METADATA, SOURCE_TO_CATALOG_PLATFORM


def catalog_platform_for_source(source: str) -> str:
    """Return the catalog platform name for a canonical source key."""
    try:
        return SOURCE_TO_CATALOG_PLATFORM[source]
    except KeyError as exc:
        raise ValueError(f"No catalog platform for source: {source!r}") from exc


def technical_key_from_profile(profile_key: str) -> str:
    """Normalize an account directory/profile key to its catalog identity key."""
    if profile_key.startswith("account-"):
        technical_key = profile_key.removeprefix("account-")
        if not technical_key:
            raise ValueError("Account profile key must include a technical key")
        return technical_key
    return profile_key


def resolve_account_id(platform: str, account_reference: str, catalog_path: Path) -> str:
    """Resolve a UUID directory, or a version-1 locator during migration."""
    if platform not in PLATFORM_ACCOUNT_METADATA:
        raise ValueError(f"Unsupported catalog platform: {platform!r}")

    catalog = load_account_catalog(catalog_path)
    normalized_key = technical_key_from_profile(account_reference)
    try:
        candidate_id = str(uuid.UUID(normalized_key))
    except (ValueError, AttributeError):
        candidate_id = None
    if candidate_id is not None:
        matches = [record for record in catalog.records
                   if record.platform == platform and record.account_id == candidate_id]
    elif catalog.requires_identity_migration:
        matches = [record for record in catalog.records
                   if record.platform == platform
                   and catalog.legacy_technical_key(record.account_id) == normalized_key]
    else:
        raise ValueError("Version-2 account paths must contain the canonical account UUID")
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one catalog account for "
            f"{platform}:{normalized_key}; found {len(matches)}"
        )
    try:
        return str(uuid.UUID(matches[0].account_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"Catalog account_id is not a valid UUID for {platform}:{normalized_key}"
        ) from exc


def stamp_account_id_rows(rows: list[dict], account_id: str) -> None:
    """Stamp account-scoped auxiliary rows before multi-account aggregation."""
    for row in rows:
        if isinstance(row, dict):
            row["account_id"] = account_id
