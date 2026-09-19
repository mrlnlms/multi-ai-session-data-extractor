"""Incremental vault writer for assets embedded in local CLI sessions."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.schema.models import Asset, AssetLink, normalize_data_relative_path

from .incremental import DEFAULT_MAX_BATCH_BYTES
from .models import AssetScope, CaptureBatch, RecordEnvelope
from .state import canonical_json
from .vault import AssetVault


@dataclass(frozen=True)
class CLIAssetObservation:
    """One embedded CLI delivery and its exact message appearance."""

    asset: Asset
    link: AssetLink
    payload: bytes
    representation_kind: str

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be bytes")
        if not self.representation_kind:
            raise ValueError("representation_kind must be a non-empty string")
        if self.asset.asset_id != self.link.asset_id:
            raise ValueError("asset and link must identify the same delivery")
        if not self.asset.is_binary_available or self.asset.asset_path is None:
            raise ValueError("CLI observations must contain available bytes and a path")
        if self.asset.size_bytes is not None and self.asset.size_bytes != len(self.payload):
            raise ValueError("asset size does not match payload")


def _record(
    record_type: str, capture_id: str, payload: dict[str, object]
) -> RecordEnvelope:
    return RecordEnvelope(record_type, 1, capture_id, True, payload)  # type: ignore[arg-type]


def _timestamp(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def _normalized_observation(item: CLIAssetObservation) -> dict[str, object]:
    asset = item.asset
    link = item.link
    digest = hashlib.sha256(item.payload).hexdigest()
    return {
        "delivery": {
            "delivery_id": asset.asset_id,
            "object_id": asset.asset_id,
            "representation_kind": item.representation_kind,
            "file_name": asset.file_name,
            "mime_type": asset.mime_type,
            "size_bytes": len(item.payload),
            "sha256": digest,
            "availability": "available",
            "created_at": _timestamp(asset.created_at),
            "metadata_json": asset.metadata_json,
            "is_preserved_missing": False,
        },
        "appearance": {
            "appearance_id": link.asset_link_id,
            "asset_link_id": link.asset_link_id,
            "delivery_id": asset.asset_id,
            "object_type": link.object_type,
            "object_id": link.object_id,
            "conversation_id": link.conversation_id,
            "message_id": link.message_id,
            "project_id": link.project_id,
            "role": link.role,
            "ordinal": link.ordinal,
            "content_block_index": link.content_block_index,
            "position_confidence": "exact",
            "projection_kind": "asset_link",
            "metadata_json": link.metadata_json,
        },
        "blob": {
            "sha256": digest,
            "size_bytes": len(item.payload),
            "mime_type": asset.mime_type,
        },
        "observation": {
            "observation_id": f"cli:{asset.asset_id}",
            "delivery_id": asset.asset_id,
            "status": "available",
            "observed_status": "available",
            "sha256": digest,
            "size_bytes": len(item.payload),
        },
        "compatibility_path": normalize_data_relative_path(asset.asset_path),
    }


def commit_cli_asset_capture(
    asset_vault: AssetVault,
    *,
    source: str,
    account_id: str | None,
    observations: tuple[CLIAssetObservation, ...],
    evidence_path: Path,
) -> str:
    """Commit one deterministic CLI parser batch before exposing projections."""

    normalized = [_normalized_observation(item) for item in observations]
    fingerprint = {
        "source": source,
        "account_id": account_id,
        "capture_method": "cli_parser_materialization",
        "evidence_path": str(Path(evidence_path)),
        "observations": normalized,
    }
    capture_id = "cli-" + hashlib.sha256(canonical_json(fingerprint)).hexdigest()
    records: list[RecordEnvelope] = [
        _record(
            "capture",
            capture_id,
            {
                "source": source,
                "account_id": account_id,
                "capture_method": "cli_parser_materialization",
                "complete_discovery": True,
                "evidence_path": str(Path(evidence_path)),
            },
        )
    ]
    blobs: dict[str, bytes] = {}
    blob_rows: set[str] = set()
    for item, row in zip(observations, normalized, strict=True):
        delivery = row["delivery"]
        appearance = row["appearance"]
        blob = row["blob"]
        observation = row["observation"]
        assert isinstance(delivery, dict)
        assert isinstance(appearance, dict)
        assert isinstance(blob, dict)
        assert isinstance(observation, dict)
        digest = blob["sha256"]
        assert isinstance(digest, str)
        records.append(_record("delivery", capture_id, delivery))
        records.append(_record("appearance", capture_id, appearance))
        if digest not in blob_rows:
            records.append(_record("blob", capture_id, blob))
            blob_rows.add(digest)
        records.append(_record("observation", capture_id, observation))
        blobs.setdefault(digest, item.payload)
    asset_vault.commit(
        CaptureBatch(
            scope=AssetScope(source, account_id),
            capture_id=capture_id,
            records=tuple(records),
            blobs=blobs,
        )
    )
    return capture_id


def _materialize_compatible_hardlink(
    vault: AssetVault, data_root: Path, item: CLIAssetObservation
) -> None:
    relative = normalize_data_relative_path(item.asset.asset_path)
    target = Path(data_root) / relative
    digest = hashlib.sha256(item.payload).hexdigest()
    blob = vault.blob_path(digest)
    vault.read_blob(digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"compatible CLI projection hash mismatch: {target}")
        if os.stat(target).st_ino == os.stat(blob).st_ino:
            return
    temporary = target.with_name(
        f".{target.name}.asset-projection-{uuid.uuid4().hex}"
    )
    try:
        os.link(blob, temporary)
        os.replace(temporary, target)
        descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


class CLIAssetCaptureSession:
    """Bound payload memory and publish legacy CLI paths as derived hardlinks."""

    def __init__(
        self,
        asset_vault: AssetVault | None,
        *,
        source: str,
        account_id: str | None,
        evidence_path: Path,
        data_root: Path,
        max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES,
    ) -> None:
        if not isinstance(max_batch_bytes, int) or max_batch_bytes <= 0:
            raise ValueError("max_batch_bytes must be a positive integer")
        self.asset_vault = asset_vault
        self.source = source
        self.account_id = account_id
        self.evidence_path = Path(evidence_path)
        self.data_root = Path(data_root)
        self.max_batch_bytes = max_batch_bytes
        self._pending: list[CLIAssetObservation] = []
        self._pending_bytes = 0
        self._observed_ids: set[str] = set()
        self._committed = False

    def observe(self, observation: CLIAssetObservation) -> None:
        if observation.asset.source != self.source or observation.link.source != self.source:
            raise ValueError("CLI observation is outside the capture source")
        if (
            observation.asset.account_id != self.account_id
            or observation.link.account_id != self.account_id
        ):
            raise ValueError("CLI observation is outside the capture account scope")
        if observation.asset.asset_id in self._observed_ids:
            raise ValueError(f"duplicate CLI delivery: {observation.asset.asset_id}")
        self._observed_ids.add(observation.asset.asset_id)
        if self.asset_vault is None:
            return
        size = len(observation.payload)
        if self._pending and self._pending_bytes + size > self.max_batch_bytes:
            self._flush()
        self._pending.append(observation)
        self._pending_bytes += size
        if self._pending_bytes >= self.max_batch_bytes:
            self._flush()

    def finish(self) -> None:
        if self.asset_vault is None:
            return
        self._flush()
        if not self._committed:
            commit_cli_asset_capture(
                self.asset_vault,
                source=self.source,
                account_id=self.account_id,
                observations=(),
                evidence_path=self.evidence_path,
            )
            self._committed = True

    def _flush(self) -> None:
        if not self._pending or self.asset_vault is None:
            return
        pending = tuple(self._pending)
        commit_cli_asset_capture(
            self.asset_vault,
            source=self.source,
            account_id=self.account_id,
            observations=pending,
            evidence_path=self.evidence_path,
        )
        for item in pending:
            _materialize_compatible_hardlink(self.asset_vault, self.data_root, item)
        self._pending.clear()
        self._pending_bytes = 0
        self._committed = True
