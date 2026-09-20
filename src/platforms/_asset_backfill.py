"""Shared mechanics for source-owned, read-only asset backfill adapters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from src.assets.contracts import AssetEvidenceContext
from src.assets.appearances import (
    link_appearance_payload,
    message_path_appearance_payload,
)
from src.assets.models import AssetScope, CaptureBatch, RecordEnvelope
from src.assets.state import canonical_json
from src.schema.models import Asset, normalize_data_relative_path


_REPRESENTATION_BY_PUBLIC_CLASS = {
    ("other", "unknown", None): "delivery",
    ("attachment", "user", False): "user_attachment",
    ("generated", "assistant", True): "assistant_generated",
    ("project_file", "user", False): "user_project_file",
    ("project_file", "unknown", None): "project_file",
    ("output", "assistant", True): "assistant_output",
    ("artifact", "assistant", True): "assistant_artifact",
    ("artifact", "platform", False): "platform_artifact",
    ("artifact", "user", False): "user_artifact",
    ("attachment", "unknown", None): "unattributed_attachment",
}


def _timestamp(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def _record(record_type: str, capture_id: str, payload: dict[str, object]) -> RecordEnvelope:
    return RecordEnvelope(record_type, 1, capture_id, True, payload)  # type: ignore[arg-type]


def _representation_kind(asset: Asset) -> str:
    key = (asset.asset_kind, asset.asset_origin, asset.is_model_generated)
    try:
        return _REPRESENTATION_BY_PUBLIC_CLASS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported legacy asset classification: {key!r}") from exc


def _available_payload(asset: Asset, data_root: Path) -> tuple[str | None, bytes | None]:
    if not asset.is_binary_available:
        if asset.asset_path is not None:
            raise ValueError(f"unavailable asset has a path: {asset.asset_id}")
        return None, None
    if asset.asset_path is None:
        raise ValueError(f"available asset has no path: {asset.asset_id}")
    relative = normalize_data_relative_path(asset.asset_path)
    path = data_root / relative
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"legacy asset path is missing: {relative}") from exc
    if asset.size_bytes is not None and len(payload) != int(asset.size_bytes):
        raise ValueError(f"legacy asset size mismatch: {asset.asset_id}")
    return hashlib.sha256(payload).hexdigest(), payload


class ProjectionEvidenceAdapter:
    """Translate the already validated public source projection without mutation."""

    def __init__(self, source: str, family: str, *, require_empty: bool = False) -> None:
        self.source = source
        self.family = family
        self.require_empty = require_empty

    def collect(self, context: AssetEvidenceContext) -> CaptureBatch:
        if context.source != self.source:
            raise ValueError(
                f"adapter {self.source!r} cannot collect source {context.source!r}"
            )
        if self.require_empty and (context.assets or context.links or context.message_paths):
            raise ValueError(f"{self.source} backfill must remain explicitly empty")

        deliveries: list[dict[str, object]] = []
        appearances: list[dict[str, object]] = []
        observations: list[dict[str, object]] = []
        blobs: dict[str, bytes] = {}
        blob_rows: dict[str, dict[str, object]] = {}

        for asset in context.assets:
            if asset.source != self.source or asset.account_id != context.account_id:
                raise ValueError(f"asset is outside adapter scope: {asset.asset_id}")
            digest, payload = _available_payload(asset, Path(context.data_root))
            if digest is not None and payload is not None:
                blobs.setdefault(digest, payload)
                blob_rows.setdefault(
                    digest,
                    {
                        "sha256": digest,
                        "size_bytes": len(payload),
                        "mime_type": asset.mime_type,
                    },
                )
            deliveries.append(
                {
                    "delivery_id": asset.asset_id,
                    "object_id": asset.asset_id,
                    "representation_kind": _representation_kind(asset),
                    "file_name": asset.file_name,
                    "mime_type": asset.mime_type,
                    "size_bytes": (
                        len(payload) if payload is not None else asset.size_bytes
                    ),
                    "sha256": digest,
                    "availability": "available" if payload is not None else "reference_only",
                    "created_at": _timestamp(asset.created_at),
                    "metadata_json": asset.metadata_json,
                    "is_preserved_missing": asset.is_preserved_missing,
                }
            )
            status = (
                "preserved_missing"
                if asset.is_preserved_missing
                else "available" if payload is not None else "reference_only"
            )
            observations.append(
                {
                    "observation_id": f"legacy-{asset.asset_id}",
                    "delivery_id": asset.asset_id,
                    "status": status,
                }
            )

        asset_ids = {asset.asset_id for asset in context.assets}
        for link in context.links:
            if link.asset_id not in asset_ids:
                raise ValueError(f"link has no delivery in batch: {link.asset_id}")
            appearances.append(link_appearance_payload(
                link, projection_order=context.link_order[link.asset_link_id]
            ))

        for item in context.message_paths:
            if item.asset_id not in asset_ids:
                raise ValueError(f"message path has no delivery in batch: {item.asset_id}")
            appearances.append(message_path_appearance_payload(
                self.source, context.account_id, item
            ))

        capture_payload: dict[str, object] = {
            "source": self.source,
            "account_id": context.account_id,
            "capture_method": "legacy_projection_backfill",
            "adapter_family": self.family,
            "evidence_paths": [str(path) for path in context.evidence_paths],
            "message_paths_authoritative": True,
        }
        fingerprint_source = {
            "capture": capture_payload,
            "deliveries": deliveries,
            "appearances": appearances,
            "blobs": list(blob_rows.values()),
            "observations": observations,
        }
        capture_id = "backfill-" + hashlib.sha256(
            canonical_json(fingerprint_source)
        ).hexdigest()
        records = [_record("capture", capture_id, capture_payload)]
        records.extend(_record("delivery", capture_id, row) for row in deliveries)
        records.extend(_record("appearance", capture_id, row) for row in appearances)
        records.extend(_record("blob", capture_id, row) for row in blob_rows.values())
        records.extend(_record("observation", capture_id, row) for row in observations)
        return CaptureBatch(
            scope=AssetScope(self.source, context.account_id),
            capture_id=capture_id,
            records=tuple(records),
            blobs=blobs,
        )
