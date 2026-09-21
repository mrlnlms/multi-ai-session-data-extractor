"""Private mapping from a capture profile to its account provenance."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.account_catalog import (
    LifecycleStatus, legacy_account_id, load_account_catalog, validate_technical_key,
)
from src.account_bindings import DEFAULT_BINDINGS_PATH, load_account_bindings
from src.platforms.registry import PLATFORM_ACCOUNT_CAPABILITIES, PLATFORM_ACCOUNT_METADATA
from src.auth_health import DEFAULT_HEALTH_PATH, load_auth_health


DEFAULT_ACCOUNTS_FILE = Path(".storage/accounts.json")
ACCOUNT_ID_ENV = "AI_ARCHIVE_ACCOUNT_ID"


@dataclass(frozen=True)
class AccountDefinition:
    """Legacy source-command defaults retained only for v1 compatibility."""

    platform: str
    key: str
    registry_key: str
    profile_prefix: str


@dataclass(frozen=True)
class AccountEvidence:
    """Independent local evidence for one account instance."""

    registry_present: bool = False
    profile_path: Path | None = None
    raw_path: Path | None = None
    merged_path: Path | None = None
    historical_path: Path | None = None

    @property
    def profile_present(self) -> bool:
        return self.profile_path is not None

    @property
    def raw_present(self) -> bool:
        return self.raw_path is not None

    @property
    def merged_present(self) -> bool:
        return self.merged_path is not None

    @property
    def historical_present(self) -> bool:
        return self.historical_path is not None


@dataclass(frozen=True)
class AccountState:
    """Read-only account inventory entry; authentication is never inferred."""

    platform: str
    key: str
    label: str | None
    evidence: AccountEvidence
    authentication: str
    account_id: str = ""
    lifecycle_status: LifecycleStatus | None = None
    authentication_method: str | None = None


@dataclass(frozen=True)
class RunnableAccount:
    account_id: str
    profile_key: str


def account_definitions(platform: str) -> tuple[AccountDefinition, ...]:
    """Return compatibility defaults for a supported web platform."""
    metadata = PLATFORM_ACCOUNT_METADATA.get(platform)
    if metadata is None:
        return ()
    return tuple(
        AccountDefinition(platform, key, metadata.registry_key, metadata.profile_prefix)
        for key in metadata.fallback_keys
    )


def account_keys(platform: str) -> tuple[str, ...]:
    """Return canonical fallback keys in their operational order."""
    return tuple(definition.key for definition in account_definitions(platform))


def default_sync_accounts(platform: str) -> tuple[str, ...]:
    """Return the unchanged compatibility order for an all-account sync."""
    return account_keys(platform)


def runnable_account_keys(platform: str) -> tuple[str, ...]:
    """Return capture targets in inventory order, excluding retained accounts."""
    return tuple(
        _observed_execution_key(state)
        for state in discover_accounts(platform)
        if state.lifecycle_status in {None, LifecycleStatus.ACTIVE}
        and not state.key.startswith("archive:")
    )


def runnable_accounts(platform: str) -> tuple[RunnableAccount, ...]:
    """Return UUID/profile pairs without making the profile an identity."""
    result = []
    metadata = PLATFORM_ACCOUNT_METADATA.get(platform)
    if metadata is None:
        return ()
    for state in discover_accounts(platform):
        if state.lifecycle_status not in {None, LifecycleStatus.ACTIVE}:
            continue
        if state.evidence.profile_path is None:
            continue
        name = state.evidence.profile_path.name
        profile_key = (
            name[len(metadata.profile_prefix):]
            if name.startswith(metadata.profile_prefix) else "default"
        )
        result.append(RunnableAccount(state.account_id, profile_key))
    return tuple(result)


def _observed_execution_key(state: AccountState) -> str:
    """Preserve the exact profile/data suffix expected by legacy sync CLIs."""
    metadata = PLATFORM_ACCOUNT_METADATA[state.platform]
    if state.evidence.profile_path is not None:
        name = state.evidence.profile_path.name
        if name.startswith(metadata.profile_prefix):
            return name[len(metadata.profile_prefix):]
    for path in (state.evidence.raw_path, state.evidence.merged_path):
        if path is not None and path.name.startswith("account-"):
            return path.name
    return state.key


def account_command_argument(platform: str, profile_key: str) -> tuple[str, str]:
    """Pass a machine-local profile locator to a source sync command."""
    capability = PLATFORM_ACCOUNT_CAPABILITIES.get(platform)
    if capability is None:
        raise ValueError(f"Platform does not support web account selection: {platform!r}")
    key = validate_technical_key(profile_key, allow_archive=False)
    return capability.sync_argument, key


def capturable_account_key(value: str) -> str:
    """Argparse-compatible validator for an explicitly selected account."""
    return validate_technical_key(value, allow_archive=False)


def load_account_registry(path: Path = DEFAULT_ACCOUNTS_FILE) -> dict[str, dict[str, str]]:
    """Load a private ``platform -> profile -> e-mail`` mapping.

    A missing file is normal on a new installation and leaves account provenance
    unset. Invalid content fails loudly instead of silently labelling an archive
    with the wrong account.
    """
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid account registry JSON: {path}") from exc

    if not isinstance(raw, Mapping):
        raise ValueError("Account registry root must be an object")

    registry: dict[str, dict[str, str]] = {}
    for platform, profiles in raw.items():
        if not isinstance(platform, str) or not isinstance(profiles, Mapping):
            raise ValueError("Account registry must map platform names to objects")
        parsed_profiles: dict[str, str] = {}
        for profile, email in profiles.items():
            if not isinstance(profile, str) or not isinstance(email, str) or not email:
                raise ValueError("Account registry profile mappings must be non-empty strings")
            parsed_profiles[profile] = email
        registry[platform] = parsed_profiles
    return registry


def account_email(platform: str, profile: str, registry_path: Path = DEFAULT_ACCOUNTS_FILE) -> str | None:
    """Return the configured e-mail for one platform/profile, if known."""
    return load_account_registry(registry_path).get(platform, {}).get(profile)


def uses_legacy_account_layout(catalog_path: Path) -> bool:
    return load_account_catalog(catalog_path).requires_identity_migration


def account_presentation(
    platform: str,
    account_reference: str,
    catalog_path: Path,
    *,
    registry_source: str,
    registry_path: Path = DEFAULT_ACCOUNTS_FILE,
) -> str | None:
    """Return catalog presentation, falling back only for legacy v1 data."""
    from src.account_identity import resolve_account_id

    catalog = load_account_catalog(catalog_path)
    account_id = resolve_account_id(platform, account_reference, catalog_path)
    record = next(item for item in catalog.records if item.account_id == account_id)
    if record.display_name:
        return record.display_name
    if record.email:
        return f"{platform} · {record.email}"
    if catalog.requires_identity_migration:
        return account_email(registry_source, account_reference, registry_path)
    return platform


def account_data_dir(base: Path, account_key: str) -> Path:
    """Return the UUID tree, with version-1 layout as finite compatibility."""
    runtime_account_id = os.environ.get(ACCOUNT_ID_ENV)
    if runtime_account_id:
        try:
            runtime_account_id = str(uuid.UUID(runtime_account_id))
        except ValueError as exc:
            raise ValueError(f"{ACCOUNT_ID_ENV} must contain a canonical UUID") from exc
        return base / f"account-{runtime_account_id}"
    catalog_path = Path("data/accounts/catalog.json")
    if catalog_path.exists() and not load_account_catalog(catalog_path).requires_identity_migration:
        raise ValueError(
            f"UUID runtime is required with catalog v2; run through the account workflow "
            f"so {ACCOUNT_ID_ENV} is set"
        )
    if account_key == "default":
        return base
    suffix = account_key if account_key.startswith("account-") else f"account-{account_key}"
    return base / suffix


def _account_path_suffix(value: str) -> str:
    return value.removeprefix("account-")


def _historical_account_key(directory_name: str) -> str | None:
    """Match the stable archive identity emitted by historical parsers."""
    normalized = re.sub(r"[^a-z0-9]+", "-", directory_name.lower()).strip("-")
    return f"archive:{normalized}" if normalized else None


def _contains_source_artifacts(path: Path) -> bool:
    ignored = {"capture_log.jsonl", "reconcile_log.jsonl", "assets_log.json"}
    try:
        for child in path.iterdir():
            if child.name.startswith("account-"):
                continue
            if child.is_file() and child.name not in ignored:
                return True
            if child.is_dir() and any(
                item.is_file() and item.name not in ignored for item in child.rglob("*")
            ):
                return True
        return False
    except OSError:
        return False


def discover_accounts(
    platform: str,
    *,
    storage_root: Path = Path(".storage"),
    raw_root: Path = Path("data/raw"),
    merged_root: Path = Path("data/merged"),
    external_root: Path = Path("data/external"),
    catalog_path: Path = Path("data/accounts/catalog.json"),
    registry_path: Path = DEFAULT_ACCOUNTS_FILE,
    bindings_path: Path | None = None,
    health_path: Path | None = None,
) -> tuple[AccountState, ...]:
    """Inventory all locally observable accounts without validating login."""
    metadata = PLATFORM_ACCOUNT_METADATA.get(platform)
    if metadata is None:
        return ()

    catalog = load_account_catalog(catalog_path)
    registry = load_account_registry(registry_path).get(metadata.registry_key, {})
    legacy_inventory = catalog.requires_identity_migration or not catalog.records
    keys = (set(metadata.fallback_keys) | {_account_path_suffix(key) for key in registry}) if legacy_inventory else set()
    catalog_records = {
        (catalog.legacy_technical_key(record.account_id) or record.account_id): record
        for record in catalog.records if record.platform == platform
    }
    health = load_auth_health(health_path or storage_root / DEFAULT_HEALTH_PATH.name)
    keys.update(catalog_records)
    profiles: dict[str, Path] = {}
    bindings = load_account_bindings(bindings_path or storage_root / DEFAULT_BINDINGS_PATH.name)

    if storage_root.exists():
        try:
            children = tuple(storage_root.iterdir())
        except OSError:
            children = ()
        for path in children:
            if not path.is_dir() or not path.name.startswith(metadata.profile_prefix):
                continue
            key = _account_path_suffix(path.name[len(metadata.profile_prefix):])
            if key:
                keys.add(key)
                profiles[key] = path
        for legacy_name in metadata.legacy_default_profiles:
            legacy_path = storage_root / legacy_name
            if legacy_path.is_dir():
                profiles.setdefault("default", legacy_path)
                keys.add("default")
    for key, record in catalog_records.items():
        binding = bindings.get(record.account_id)
        if binding is None:
            continue
        bound_path = storage_root / f"{metadata.profile_prefix}{binding.profile_key}"
        if record.platform == "Perplexity" and binding.profile_key == "default":
            legacy_path = storage_root / "perplexity-profile"
            if legacy_path.is_dir():
                bound_path = legacy_path
        if bound_path.is_dir():
            profiles[key] = bound_path

    raw_platform = raw_root / platform
    merged_platform = merged_root / platform
    raw_paths: dict[str, Path] = {}
    merged_paths: dict[str, Path] = {}
    historical_paths: dict[str, Path] = {}
    for base, paths in ((raw_platform, raw_paths), (merged_platform, merged_paths)):
        if base.exists():
            try:
                children = tuple(base.iterdir())
            except OSError:
                children = ()
            for path in children:
                if path.is_dir() and path.name.startswith("account-"):
                    key = _account_path_suffix(path.name)
                    if key:
                        keys.add(key)
                        paths[key] = path
            if _contains_source_artifacts(base):
                paths["default"] = base
                keys.add("default")

    if metadata.historical_archive_root:
        archive_root = external_root / metadata.historical_archive_root
        if archive_root.exists():
            try:
                archives = tuple(archive_root.iterdir())
            except OSError:
                archives = ()
            for path in archives:
                if not path.is_dir():
                    continue
                key = _historical_account_key(path.name)
                if key:
                    keys.add(key)
                    historical_paths[key] = path

    fallback_order = {key: index for index, key in enumerate(metadata.fallback_keys)}
    ordered_keys = sorted(keys, key=lambda key: (fallback_order.get(key, len(fallback_order)), key))
    states = []
    for key in ordered_keys:
        registry_lookup = key if key in registry else f"account-{key}"
        catalog_record = catalog_records.get(key)
        legacy_label = registry.get(registry_lookup)
        label = (
            catalog_record.display_name
            if catalog_record is not None and catalog_record.display_name
            else catalog_record.email
            if catalog_record is not None and catalog_record.email
            else legacy_label
        )
        evidence = AccountEvidence(
            registry_present=legacy_label is not None,
            profile_path=profiles.get(key),
            raw_path=raw_paths.get(key),
            merged_path=merged_paths.get(key),
            historical_path=historical_paths.get(key),
        )
        account_id = catalog_record.account_id if catalog_record is not None else legacy_account_id(platform, key)
        observation = health.get(account_id)
        authentication = (
            observation.status.value if observation is not None
            else ("unknown" if evidence.profile_present else "not_configured")
        )
        states.append(AccountState(
            platform,
            key,
            label,
            evidence,
            authentication,
            account_id=account_id,
            lifecycle_status=(
                catalog_record.lifecycle_status if catalog_record is not None else None
            ),
            authentication_method=(
                observation.evidence_method.value
                if observation is not None and observation.evidence_method is not None else None
            ),
        ))
    return tuple(states)
