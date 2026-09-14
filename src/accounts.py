"""Private mapping from a capture profile to its account provenance."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.platforms.registry import PLATFORM_ACCOUNT_METADATA


DEFAULT_ACCOUNTS_FILE = Path(".storage/accounts.json")


@dataclass(frozen=True)
class AccountDefinition:
    """Canonical technical identity used by the current filesystem layout."""

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


def account_data_dir(base: Path, account_key: str) -> Path:
    """Return the per-account tree without changing the legacy default path."""
    if account_key == "default":
        return base
    suffix = account_key if account_key.startswith("account-") else f"account-{account_key}"
    return base / suffix


def _technical_key(value: str) -> str:
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
    registry_path: Path = DEFAULT_ACCOUNTS_FILE,
) -> tuple[AccountState, ...]:
    """Inventory all locally observable accounts without validating login."""
    metadata = PLATFORM_ACCOUNT_METADATA.get(platform)
    if metadata is None:
        return ()

    registry = load_account_registry(registry_path).get(metadata.registry_key, {})
    keys = set(metadata.fallback_keys) | {_technical_key(key) for key in registry}
    profiles: dict[str, Path] = {}

    if storage_root.exists():
        try:
            children = tuple(storage_root.iterdir())
        except OSError:
            children = ()
        for path in children:
            if not path.is_dir() or not path.name.startswith(metadata.profile_prefix):
                continue
            key = _technical_key(path.name[len(metadata.profile_prefix):])
            if key:
                keys.add(key)
                profiles[key] = path
        for legacy_name in metadata.legacy_default_profiles:
            legacy_path = storage_root / legacy_name
            if legacy_path.is_dir():
                profiles.setdefault("default", legacy_path)
                keys.add("default")

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
                    key = _technical_key(path.name)
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
        label = registry.get(registry_lookup)
        evidence = AccountEvidence(
            registry_present=label is not None,
            profile_path=profiles.get(key),
            raw_path=raw_paths.get(key),
            merged_path=merged_paths.get(key),
            historical_path=historical_paths.get(key),
        )
        authentication = "unknown" if evidence.profile_present else "not_configured"
        states.append(AccountState(platform, key, label, evidence, authentication))
    return tuple(states)
