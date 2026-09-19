"""Contracts shared by read-only source adapters and the backfill workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from src.schema.models import Asset, AssetLink

from .models import CaptureBatch


@dataclass(frozen=True)
class SourceInputs:
    """Explicit read-only inputs for one legacy source projection."""

    data_root: Path
    assets_path: Path
    asset_links_path: Path
    messages_path: Path
    evidence_paths: tuple[Path, ...] = ()
    max_batch_bytes: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_root", Path(self.data_root))
        object.__setattr__(self, "assets_path", Path(self.assets_path))
        object.__setattr__(self, "asset_links_path", Path(self.asset_links_path))
        object.__setattr__(self, "messages_path", Path(self.messages_path))
        object.__setattr__(
            self, "evidence_paths", tuple(Path(path) for path in self.evidence_paths)
        )
        if not isinstance(self.max_batch_bytes, int) or self.max_batch_bytes <= 0:
            raise ValueError("max_batch_bytes must be a positive integer")


@dataclass(frozen=True)
class MessagePathEvidence:
    """One ordered legacy Message.asset_paths occurrence."""

    asset_id: str
    conversation_id: str
    message_id: str
    ordinal: int


@dataclass(frozen=True)
class AssetEvidenceContext:
    """One bounded source/account chunk translated into an atomic capture."""

    source: str
    account_id: str | None
    assets: tuple[Asset, ...]
    links: tuple[AssetLink, ...]
    link_order: Mapping[str, int]
    message_paths: tuple[MessagePathEvidence, ...]
    data_root: Path
    evidence_paths: tuple[Path, ...]


class AssetEvidenceAdapter(Protocol):
    """Translate preserved source evidence into one durable capture batch."""

    source: str
    family: str

    def collect(self, context: AssetEvidenceContext) -> CaptureBatch:
        raise NotImplementedError


@dataclass(frozen=True)
class ProjectionReport:
    """Materialized compatibility projection and its measurable coverage."""

    source: str
    scope_count: int
    commit_count: int
    asset_count: int
    link_count: int
    available_count: int
    message_path_count: int
    evidence_paths: tuple[str, ...]
    assets: tuple[Asset, ...]
    links: tuple[AssetLink, ...]
    message_paths: Mapping[str, tuple[str, ...]]
