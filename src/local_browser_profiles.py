"""Machine-local browser executable and directory selection for durable groups."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.browser_profile_catalog import BrowserProfileCatalog, canonical_uuid


LOCAL_VERSION = 1
DEFAULT_LOCAL_PATH = Path(".storage/browser-profile-config.json")
BrowserChannel = Literal["chromium", "chrome"]
_SAFE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class LocalBrowserProfile:
    profile_id: str
    channel: BrowserChannel
    directory: str


@dataclass(frozen=True)
class LocalBrowserProfiles:
    version: int = LOCAL_VERSION
    records: tuple[LocalBrowserProfile, ...] = ()

    def get(self, profile_id: str) -> LocalBrowserProfile | None:
        return next((item for item in self.records if item.profile_id == profile_id), None)


def _validate(config: LocalBrowserProfiles) -> None:
    if config.version != LOCAL_VERSION:
        raise ValueError(f"Unsupported local browser-profile version: {config.version!r}")
    seen: set[str] = set()
    directories: set[str] = set()
    for item in config.records:
        canonical_uuid(item.profile_id, "profile_id")
        if item.channel not in {"chromium", "chrome"}:
            raise ValueError(f"Unsupported browser channel: {item.channel!r}")
        validate_profile_directory(item.directory)
        if item.profile_id in seen:
            raise ValueError(f"Duplicate local browser profile: {item.profile_id}")
        if item.directory in directories:
            raise ValueError(f"Browser directory assigned to more than one group: {item.directory}")
        seen.add(item.profile_id)
        directories.add(item.directory)


def validate_profile_directory(value: object) -> str:
    """Accept only a safe path relative to ``.storage/``."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Browser-profile directory must be a safe relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or not _SAFE_PART.fullmatch(part) for part in parts):
        raise ValueError("Browser-profile directory must be a safe relative path")
    return value


def load_local_browser_profiles(path: Path = DEFAULT_LOCAL_PATH) -> LocalBrowserProfiles:
    if not path.exists():
        return LocalBrowserProfiles()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid local browser-profile JSON: {path}") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"version", "profiles"}:
        raise ValueError("Local browser-profile root fields must be version and profiles")
    if type(raw["version"]) is not int or raw["version"] != LOCAL_VERSION:
        raise ValueError(f"Unsupported local browser-profile version: {raw['version']!r}")
    if not isinstance(raw["profiles"], list):
        raise ValueError("Local browser-profile profiles must be an array")
    records = []
    for item in raw["profiles"]:
        if not isinstance(item, Mapping) or set(item) != {"profile_id", "channel", "directory"}:
            raise ValueError("Local browser-profile fields must be profile_id, channel and directory")
        if not isinstance(item["channel"], str):
            raise ValueError("Local browser channel must be a string")
        records.append(LocalBrowserProfile(
            canonical_uuid(item["profile_id"], "profile_id"), item["channel"],
            validate_profile_directory(item["directory"]),
        ))
    config = LocalBrowserProfiles(records=tuple(records))
    _validate(config)
    return config


def serialize_local_browser_profiles(config: LocalBrowserProfiles) -> str:
    _validate(config)
    payload = {"version": config.version, "profiles": [
        {"profile_id": item.profile_id, "channel": item.channel, "directory": item.directory}
        for item in config.records
    ]}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def set_local_browser_profile(
    config: LocalBrowserProfiles, catalog: BrowserProfileCatalog, *,
    profile_id: str, channel: BrowserChannel, storage_root: Path = Path(".storage"),
    directory: str | None = None, adopt_existing: bool = False,
) -> LocalBrowserProfiles:
    canonical_uuid(profile_id, "profile_id")
    if catalog.get(profile_id) is None:
        raise ValueError(f"Unknown browser profile: {profile_id}")
    if channel not in {"chromium", "chrome"}:
        raise ValueError(f"Unsupported browser channel: {channel!r}")
    previous = config.get(profile_id)
    directory = validate_profile_directory(directory or f"browser-profiles/{profile_id}")
    path = storage_root / directory
    if not path.resolve().is_relative_to(storage_root.resolve()):
        raise ValueError("Browser-profile directory leaves the local storage root")
    if path.is_symlink():
        raise ValueError("Browser-profile directory must not be a symlink")
    if path.exists() and not path.is_dir():
        raise ValueError("Browser-profile path is not a directory")
    if adopt_existing and not path.is_dir():
        raise ValueError("Existing browser-profile directory is missing")
    if previous is None and path.is_dir() and any(path.iterdir()) and not adopt_existing:
        raise ValueError("Existing browser-profile directory has no channel record")
    if previous is not None and (previous.channel != channel or previous.directory != directory):
        if (storage_root / previous.directory).exists():
            raise ValueError("Cannot change the channel or directory of an existing local profile")
    replacement = LocalBrowserProfile(profile_id, channel, directory)
    after = LocalBrowserProfiles(records=tuple(
        item for item in config.records if item.profile_id != profile_id
    ) + (replacement,))
    _validate(after)
    return after


def browser_profile_path(
    storage_root: Path, profile_id: str, config: LocalBrowserProfiles | None = None,
) -> Path:
    canonical_uuid(profile_id, "profile_id")
    record = config.get(profile_id) if config else None
    directory = record.directory if record else f"browser-profiles/{profile_id}"
    path = storage_root / validate_profile_directory(directory)
    if not path.resolve().is_relative_to(storage_root.resolve()):
        raise ValueError("Browser-profile directory leaves the local storage root")
    return path


def write_local_browser_profiles_atomic(
    path: Path, config: LocalBrowserProfiles, *, expected_before: LocalBrowserProfiles,
) -> None:
    serialized = serialize_local_browser_profiles(config)
    if load_local_browser_profiles(path) != expected_before:
        raise ValueError(f"Refusing stale local browser-profile write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        if load_local_browser_profiles(path) != expected_before:
            raise ValueError(f"Refusing stale local browser-profile write: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
