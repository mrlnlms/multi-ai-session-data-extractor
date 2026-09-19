from __future__ import annotations

from pathlib import Path

import pytest

from src.platforms.registry import PLATFORM_COMMAND_PACKAGES
from src.assets.runtime import (
    ASSET_DATA_ROOT_ENV,
    ASSET_MODE_ENV,
    ASSET_VAULT_ROOT_ENV,
    AssetMode,
    load_asset_runtime,
)


def test_runtime_defaults_to_canonical_vault(monkeypatch):
    monkeypatch.delenv(ASSET_MODE_ENV, raising=False)
    monkeypatch.delenv(ASSET_VAULT_ROOT_ENV, raising=False)
    monkeypatch.delenv(ASSET_DATA_ROOT_ENV, raising=False)

    runtime = load_asset_runtime("chatgpt")

    assert runtime.mode is AssetMode.VAULT
    assert runtime.vault is not None
    assert runtime.vault.root == Path("data/assets")
    assert runtime.reader is not None
    assert runtime.reader.data_root == Path("data")


def test_runtime_keeps_explicit_legacy_rollback(monkeypatch):
    monkeypatch.setenv(ASSET_MODE_ENV, "legacy")
    monkeypatch.delenv(ASSET_VAULT_ROOT_ENV, raising=False)
    monkeypatch.delenv(ASSET_DATA_ROOT_ENV, raising=False)

    runtime = load_asset_runtime("chatgpt")

    assert runtime.mode is AssetMode.LEGACY
    assert runtime.vault is None
    assert runtime.reader is None


def test_runtime_builds_vault_and_reader_from_explicit_roots(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    vault_root = data_root / "assets"
    monkeypatch.setenv(ASSET_MODE_ENV, "vault")
    monkeypatch.setenv(ASSET_VAULT_ROOT_ENV, str(vault_root))
    monkeypatch.setenv(ASSET_DATA_ROOT_ENV, str(data_root))

    runtime = load_asset_runtime("qwen")

    assert runtime.mode is AssetMode.VAULT
    assert runtime.vault is not None
    assert runtime.vault.root == vault_root
    assert runtime.reader is not None
    assert runtime.reader.data_root == data_root


@pytest.mark.parametrize("value", ["", "auto", "VAULT"])
def test_runtime_rejects_implicit_or_invalid_modes(value, monkeypatch):
    monkeypatch.setenv(ASSET_MODE_ENV, value)

    with pytest.raises(ValueError, match="legacy or vault"):
        load_asset_runtime("gemini")


def test_runtime_rejects_empty_root_override_in_vault_mode(tmp_path, monkeypatch):
    monkeypatch.setenv(ASSET_MODE_ENV, "vault")
    monkeypatch.setenv(ASSET_VAULT_ROOT_ENV, str(tmp_path / "assets"))
    monkeypatch.setenv(ASSET_DATA_ROOT_ENV, "")

    with pytest.raises(ValueError, match=ASSET_DATA_ROOT_ENV):
        load_asset_runtime("gemini")


def test_every_source_sync_consumes_the_explicit_runtime_contract():
    for package in PLATFORM_COMMAND_PACKAGES.values():
        module_path = package.replace(".", "/") + "/sync.py"
        source = Path(module_path).read_text(encoding="utf-8")
        assert "load_asset_runtime(" in source, module_path
