"""Explicit read boundary between parsers and the durable asset vault."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Protocol

from src.schema.models import Asset, AssetLink, Message

from .models import AssetScope
from .projection import AssetProjection, project_assets
from .vault import AssetVault


class AssetReader(Protocol):
    """Provide a verified compatibility projection for one durable scope."""

    def projection_for(
        self, source: str, account_id: str | None
    ) -> AssetProjection:
        raise NotImplementedError


@dataclass(frozen=True)
class VaultAssetReader:
    """Read projections from an explicitly supplied vault and data root."""

    vault: AssetVault
    data_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_root", Path(self.data_root))

    def projection_for(
        self, source: str, account_id: str | None
    ) -> AssetProjection:
        state = self.vault.load_state(AssetScope(source, account_id))
        return project_assets(state, self.data_root)


def combine_asset_projections(
    reader: AssetReader,
    source: str,
    account_ids: Iterable[str | None],
) -> AssetProjection:
    """Combine explicitly requested scopes while preserving caller order."""
    ordered_accounts: list[str | None] = []
    for account_id in account_ids:
        if account_id not in ordered_accounts:
            ordered_accounts.append(account_id)
    if not ordered_accounts:
        ordered_accounts.append(None)

    assets: list[Asset] = []
    links: list[AssetLink] = []
    message_paths: dict[str, list[str]] = {}
    for account_id in ordered_accounts:
        projection = reader.projection_for(source, account_id)
        assets.extend(projection.assets)
        links.extend(projection.links)
        for message_id, paths in projection.message_paths.items():
            destination = message_paths.setdefault(message_id, [])
            for path in paths:
                if path not in destination:
                    destination.append(path)
    return AssetProjection(
        assets=tuple(assets),
        links=tuple(links),
        message_paths=MappingProxyType(
            {message_id: tuple(paths) for message_id, paths in message_paths.items()}
        ),
    )


def apply_asset_projection(
    messages: Iterable[Message], projection: AssetProjection
) -> None:
    """Replace legacy message paths with the reader's authoritative projection."""
    for message in messages:
        paths = projection.message_paths.get(message.message_id)
        message.asset_paths = list(paths) if paths else None
