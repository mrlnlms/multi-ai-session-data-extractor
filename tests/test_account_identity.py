import json

import pytest

from src.account_catalog import legacy_account_id
from src.account_identity import (
    catalog_platform_for_source,
    resolve_account_id,
    technical_key_from_profile,
)
from src.platforms.registry import PLATFORM_ACCOUNT_METADATA


def _write_catalog(tmp_path, *, platform="ChatGPT", technical_key="2", account_id=None):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "version": 1,
        "accounts": [{
            "account_id": account_id or legacy_account_id(platform, technical_key),
            "platform": platform,
            "technical_key": technical_key,
            "lifecycle_status": "active",
            "created_at": "2026-09-13T00:00:00Z",
            "updated_at": "2026-09-13T00:00:00Z",
        }],
    }))
    return path


@pytest.mark.parametrize(
    ("profile_key", "expected"),
    [
        ("account-2", "2"),
        ("default", "default"),
        ("3", "3"),
        ("archive:legacy", "archive:legacy"),
    ],
)
def test_technical_key_from_profile(profile_key, expected):
    assert technical_key_from_profile(profile_key) == expected


@pytest.mark.parametrize(
    ("platform", "metadata"),
    PLATFORM_ACCOUNT_METADATA.items(),
)
def test_every_web_source_maps_to_catalog_platform(platform, metadata):
    assert catalog_platform_for_source(metadata.registry_key) == platform


def test_unknown_source_fails_closed():
    with pytest.raises(ValueError, match="catalog platform"):
        catalog_platform_for_source("codex")


def test_resolve_account_id_uses_catalog_identity(tmp_path):
    account_id = legacy_account_id("ChatGPT", "2")
    catalog = _write_catalog(tmp_path, account_id=account_id)
    assert resolve_account_id("ChatGPT", "account-2", catalog) == account_id


def test_missing_web_identity_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="canonical account UUID"):
        resolve_account_id("Kimi", "default", tmp_path / "missing.json")


def test_wrong_technical_key_fails_closed(tmp_path):
    catalog = _write_catalog(tmp_path)
    with pytest.raises(ValueError, match="found 0"):
        resolve_account_id("ChatGPT", "account-3", catalog)
