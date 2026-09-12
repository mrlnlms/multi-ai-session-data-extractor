"""Private mapping from a capture profile to its account provenance."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


DEFAULT_ACCOUNTS_FILE = Path(".storage/accounts.json")


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
