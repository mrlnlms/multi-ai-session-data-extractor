"""Validated process boundary for explicit legacy or vault asset execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .reader import VaultAssetReader
from .vault import AssetVault

ASSET_MODE_ENV = "AI_ARCHIVE_ASSET_MODE"
ASSET_VAULT_ROOT_ENV = "AI_ARCHIVE_ASSET_VAULT_ROOT"
ASSET_DATA_ROOT_ENV = "AI_ARCHIVE_ASSET_DATA_ROOT"


class AssetMode(str, Enum):
    LEGACY = "legacy"
    VAULT = "vault"


@dataclass(frozen=True)
class AssetRuntime:
    """Dependencies selected explicitly for one source subprocess."""

    source: str
    mode: AssetMode
    vault: AssetVault | None
    reader: VaultAssetReader | None


def load_asset_runtime(source: str) -> AssetRuntime:
    """Build vault dependencies from a validated environment contract."""
    raw_mode = os.environ.get(ASSET_MODE_ENV, AssetMode.VAULT.value)
    try:
        mode = AssetMode(raw_mode)
    except ValueError as exc:
        raise ValueError(
            f"{ASSET_MODE_ENV} must be legacy or vault, got {raw_mode!r}"
        ) from exc

    if mode is AssetMode.LEGACY:
        return AssetRuntime(source, mode, None, None)

    raw_vault_root = os.environ.get(ASSET_VAULT_ROOT_ENV, "data/assets")
    raw_data_root = os.environ.get(ASSET_DATA_ROOT_ENV, "data")
    if not raw_vault_root:
        raise ValueError(f"{ASSET_VAULT_ROOT_ENV} is required in vault mode")
    if not raw_data_root:
        raise ValueError(f"{ASSET_DATA_ROOT_ENV} is required in vault mode")

    vault = AssetVault(Path(raw_vault_root))
    reader = VaultAssetReader(vault, Path(raw_data_root))
    return AssetRuntime(source, mode, vault, reader)


def asset_subprocess_env(
    mode: str | AssetMode,
    *,
    vault_root: Path | None,
    data_root: Path | None,
) -> dict[str, str]:
    """Return the complete environment delta for one configured source."""
    try:
        selected = mode if isinstance(mode, AssetMode) else AssetMode(mode)
    except ValueError as exc:
        raise ValueError(f"asset mode must be legacy or vault, got {mode!r}") from exc
    env = {ASSET_MODE_ENV: selected.value}
    if selected is AssetMode.LEGACY:
        return env
    if vault_root is None or data_root is None:
        raise ValueError("vault_root and data_root are required in vault mode")
    env[ASSET_VAULT_ROOT_ENV] = str(Path(vault_root))
    env[ASSET_DATA_ROOT_ENV] = str(Path(data_root))
    return env


def runtime_account_id(
    runtime: AssetRuntime,
    platform: str,
    profile_key: str,
    *,
    explicit: str | None = None,
    catalog_path: Path = Path("data/accounts/catalog.json"),
) -> str | None:
    """Resolve the durable account UUID only when vault mode selected it."""
    from src.accounts import ACCOUNT_ID_ENV
    runtime_account = os.environ.get(ACCOUNT_ID_ENV)
    if runtime_account:
        if explicit is not None and explicit != runtime_account:
            raise ValueError("Explicit account_id disagrees with the runtime account UUID")
        return runtime_account
    if explicit is not None or runtime.mode is AssetMode.LEGACY:
        return explicit
    from src.account_identity import resolve_account_id

    return resolve_account_id(platform, profile_key, catalog_path)
