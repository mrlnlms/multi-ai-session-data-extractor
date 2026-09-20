"""Compatibility projection from durable vault state to the published schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from src.schema.models import Asset, AssetLink, make_asset_link_id, normalize_data_relative_path

from .models import AssetState, RecordEnvelope, validate_digest
from .vault import IntegrityError


@dataclass(frozen=True)
class _Classification:
    asset_kind: str
    asset_origin: str
    is_model_generated: bool | None


_REPRESENTATION_CLASSES = {
    "delivery": _Classification("other", "unknown", None),
    "user_attachment": _Classification("attachment", "user", False),
    "assistant_generated": _Classification("generated", "assistant", True),
    "project_file": _Classification("project_file", "unknown", None),
    "user_project_file": _Classification("project_file", "user", False),
    "assistant_output": _Classification("output", "assistant", True),
    "text_artifact_envelope": _Classification("output", "assistant", True),
    "assistant_artifact": _Classification("artifact", "assistant", True),
    "platform_artifact": _Classification("artifact", "platform", False),
    "user_artifact": _Classification("artifact", "user", False),
    "unattributed_attachment": _Classification("attachment", "unknown", None),
}

_OBSERVATION_STATUSES = frozenset({"available", "preserved_missing", "reference_only"})


@dataclass(frozen=True)
class AssetProjection:
    """Current-schema materialization for one source/account state."""

    assets: tuple[Asset, ...]
    links: tuple[AssetLink, ...]
    message_paths: Mapping[str, tuple[str, ...]]


def _required_string(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(payload: dict[str, object], name: str) -> str | None:
    value = payload.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string or None")
    return value


def _optional_index(payload: dict[str, object], name: str) -> int | None:
    value = payload.get(name)
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ValueError(f"{name} must be a nonnegative integer or None")
    return value


def _record_payloads_match(
    record_type: str,
    left: dict[str, object],
    right: dict[str, object],
) -> bool:
    if left == right:
        return True
    if record_type != "appearance":
        return False
    # Backfills persisted the public link order, while the incremental CLI
    # writer deliberately omitted it. Ordering is projection metadata rather
    # than appearance identity; every semantic field must still match.
    left_semantic = {
        key: value for key, value in left.items() if key != "projection_order"
    }
    right_semantic = {
        key: value for key, value in right.items() if key != "projection_order"
    }
    return left_semantic == right_semantic


def _unique_records(
    records: tuple[RecordEnvelope, ...], record_type: str, key_name: str
) -> tuple[RecordEnvelope, ...]:
    ordered: dict[str, RecordEnvelope] = {}
    for record in records:
        if record.record_type != record_type:
            continue
        key = _required_string(record.payload, key_name)
        previous = ordered.get(key)
        if previous is not None and not _record_payloads_match(
            record_type, previous.payload, record.payload
        ):
            raise ValueError(f"conflicting {record_type} record: {key}")
        ordered.setdefault(key, record)
    return tuple(ordered.values())


def _latest_observations(state: AssetState) -> dict[str, str]:
    latest: dict[str, str] = {}
    for record in state.records:
        if record.record_type != "observation":
            continue
        delivery_id = _required_string(record.payload, "delivery_id")
        status = _required_string(record.payload, "status")
        if status not in _OBSERVATION_STATUSES:
            raise ValueError(f"unsupported observation status: {status!r}")
        latest[delivery_id] = status
    return latest


def _blob_sizes(state: AssetState) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for record in state.records:
        if record.record_type != "blob":
            continue
        digest = validate_digest(_required_string(record.payload, "sha256"))
        size = record.payload.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise IntegrityError(f"blob record has invalid size: {digest}")
        previous = sizes.get(digest)
        if previous is not None and previous != size:
            raise IntegrityError(f"conflicting blob size: {digest}")
        sizes[digest] = size
    return sizes


def _verified_blob_path(
    data_root: Path,
    digest: str,
    expected_size: int,
    delivery_size: object,
) -> str:
    relative = normalize_data_relative_path(
        f"assets/blobs/sha256/{digest[:2]}/{digest}"
    )
    path = data_root / relative
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise IntegrityError(f"missing blob: {digest}") from exc
    if len(payload) != expected_size:
        raise IntegrityError(f"blob size mismatch: {digest}")
    if hashlib.sha256(payload).hexdigest() != digest:
        raise IntegrityError(f"blob checksum mismatch: {digest}")
    if delivery_size is not None and delivery_size != expected_size:
        raise IntegrityError(f"delivery size does not match blob: {digest}")
    return relative


def _project_asset(
    state: AssetState,
    record: RecordEnvelope,
    data_root: Path,
    blob_sizes: dict[str, int],
    observations: dict[str, str],
) -> Asset:
    payload = record.payload
    delivery_id = _required_string(payload, "delivery_id")
    object_id = _required_string(payload, "object_id")
    representation_kind = _required_string(payload, "representation_kind")
    try:
        classification = _REPRESENTATION_CLASSES[representation_kind]
    except KeyError as exc:
        raise ValueError(
            f"unsupported representation_kind: {representation_kind!r}"
        ) from exc

    availability = _required_string(payload, "availability")
    if availability not in {"available", "reference_only"}:
        raise ValueError(f"unsupported delivery availability: {availability!r}")
    digest_value = payload.get("sha256")
    asset_path: str | None = None
    if availability == "available":
        if not isinstance(digest_value, str):
            raise IntegrityError(f"available delivery has no sha256: {delivery_id}")
        digest = validate_digest(digest_value)
        if digest not in blob_sizes:
            raise IntegrityError(f"available delivery has no blob record: {digest}")
        asset_path = _verified_blob_path(
            data_root, digest, blob_sizes[digest], payload.get("size_bytes")
        )
    elif digest_value is not None:
        raise ValueError(f"reference-only delivery has sha256: {delivery_id}")

    status = observations.get(delivery_id)
    if status == "available" and asset_path is None:
        raise IntegrityError(f"available observation has no verified blob: {delivery_id}")
    if status == "reference_only" and asset_path is not None:
        raise ValueError(f"reference-only observation has available bytes: {delivery_id}")

    has_metadata_value = "metadata_json" in payload
    metadata_value = payload.get("metadata_json")
    if metadata_value is not None and not isinstance(metadata_value, str):
        raise ValueError("metadata_json must be a string or None")
    metadata = {
        "capture_id": record.capture_id,
        "object_id": object_id,
        "representation_kind": representation_kind,
        "sha256": digest_value,
    }
    created_at_value = payload.get("created_at")
    if created_at_value is not None and not isinstance(created_at_value, str):
        raise ValueError("created_at must be an ISO string or None")
    preserved_value = payload.get("is_preserved_missing", False)
    if preserved_value is not None and not isinstance(preserved_value, bool):
        raise ValueError("is_preserved_missing must be a boolean or None")
    size_value = payload.get("size_bytes")
    if size_value is not None and (
        not isinstance(size_value, int) or isinstance(size_value, bool) or size_value < 0
    ):
        raise ValueError("size_bytes must be a nonnegative integer or None")
    return Asset(
        asset_id=delivery_id,
        source=state.scope.source,
        account_id=state.scope.account_id,
        asset_kind=classification.asset_kind,
        asset_origin=classification.asset_origin,
        file_name=_optional_string(payload, "file_name"),
        mime_type=_optional_string(payload, "mime_type"),
        size_bytes=size_value,
        asset_path=asset_path,
        is_model_generated=classification.is_model_generated,
        is_preserved_missing=(
            True if status == "preserved_missing" else preserved_value
        ),
        is_binary_available=asset_path is not None,
        created_at=pd.Timestamp(created_at_value) if created_at_value is not None else None,
        metadata_json=(
            metadata_value
            if has_metadata_value
            else json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        ),
    )


def _project_link(state: AssetState, record: RecordEnvelope) -> AssetLink | None:
    payload = record.payload
    projection_kind = payload.get("projection_kind", "asset_link")
    if projection_kind == "message_path":
        return None
    if projection_kind != "asset_link":
        raise ValueError(f"unsupported appearance projection_kind: {projection_kind!r}")
    delivery_id = _required_string(payload, "delivery_id")
    object_type = payload.get("object_type")
    object_id = payload.get("object_id")
    confidence = _required_string(payload, "position_confidence")
    if object_type is None and object_id is None:
        if confidence != "unproven":
            raise ValueError("unpositioned appearance must have unproven confidence")
        return None
    if not isinstance(object_type, str) or not object_type:
        raise ValueError("object_type must be a non-empty string for a positioned appearance")
    if not isinstance(object_id, str) or not object_id:
        raise ValueError("object_id must be a non-empty string for a positioned appearance")
    conversation_id = _optional_string(payload, "conversation_id")
    message_id = _optional_string(payload, "message_id")
    project_id = _optional_string(payload, "project_id")
    role = _required_string(payload, "role")
    ordinal = _optional_index(payload, "ordinal")
    content_block_index = _optional_index(payload, "content_block_index")
    has_metadata_value = "metadata_json" in payload
    metadata_value = payload.get("metadata_json")
    if metadata_value is not None and not isinstance(metadata_value, str):
        raise ValueError("metadata_json must be a string or None")
    metadata = {
        "appearance_id": _required_string(payload, "appearance_id"),
        "capture_id": record.capture_id,
        "position_confidence": confidence,
    }
    asset_link_id = payload.get("asset_link_id")
    if asset_link_id is not None and not isinstance(asset_link_id, str):
        raise ValueError("asset_link_id must be a string or None")
    return AssetLink(
        asset_link_id=(
            asset_link_id
            if asset_link_id is not None
            else make_asset_link_id(
                state.scope.source,
                state.scope.account_id,
                delivery_id,
                object_type,
                object_id,
                role,
                ordinal,
                content_block_index,
            )
        ),
        source=state.scope.source,
        account_id=state.scope.account_id,
        asset_id=delivery_id,
        object_type=object_type,
        object_id=object_id,
        conversation_id=conversation_id,
        message_id=message_id,
        project_id=project_id,
        role=role,
        ordinal=ordinal,
        content_block_index=content_block_index,
        metadata_json=(
            metadata_value
            if has_metadata_value
            else json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        ),
    )


def project_assets(state: AssetState, data_root: Path) -> AssetProjection:
    """Project one committed scope while exposing only verified blob paths."""
    if not isinstance(state, AssetState):
        raise TypeError("state must be an AssetState")
    data_root = Path(data_root)
    deliveries = _unique_records(state.records, "delivery", "delivery_id")
    appearances = _unique_records(state.records, "appearance", "appearance_id")
    observations = _latest_observations(state)
    blob_sizes = _blob_sizes(state)
    assets = tuple(
        _project_asset(state, record, data_root, blob_sizes, observations)
        for record in deliveries
    )
    asset_ids = {asset.asset_id for asset in assets}

    links_with_order: list[tuple[int, int, AssetLink]] = []
    for sequence, record in enumerate(appearances):
        delivery_id = _required_string(record.payload, "delivery_id")
        if delivery_id not in asset_ids:
            raise ValueError(f"appearance has no preserved delivery: {delivery_id}")
        link = _project_link(state, record)
        if link is not None:
            projection_order = record.payload.get("projection_order", sequence)
            if not isinstance(projection_order, int) or isinstance(projection_order, bool):
                raise ValueError("projection_order must be an integer")
            links_with_order.append((projection_order, sequence, link))
    links = [link for _, _, link in sorted(links_with_order)]

    asset_paths = {asset.asset_id: asset.asset_path for asset in assets}
    has_explicit_message_paths = any(
        record.payload.get("projection_kind") == "message_path"
        for record in appearances
    ) or any(
        record.record_type == "capture"
        and record.payload.get("message_paths_authoritative") is True
        for record in state.records
    )
    ordered_paths: dict[str, list[tuple[int, int, str]]] = {}
    for sequence, record in enumerate(appearances):
        payload = record.payload
        message_id = _optional_string(payload, "message_id")
        if message_id is None:
            continue
        projection_kind = payload.get("projection_kind", "asset_link")
        if has_explicit_message_paths and projection_kind != "message_path":
            continue
        path = asset_paths[_required_string(payload, "delivery_id")]
        if path is None:
            continue
        ordinal = _optional_index(payload, "ordinal")
        ordered_paths.setdefault(message_id, []).append(
            (ordinal if ordinal is not None else sequence, sequence, path)
        )
    paths_by_message: dict[str, tuple[str, ...]] = {}
    for message_id, values in ordered_paths.items():
        ordered = [path for _, _, path in sorted(values)]
        if has_explicit_message_paths:
            paths_by_message[message_id] = tuple(ordered)
            continue
        unique: list[str] = []
        for path in ordered:
            if path not in unique:
                unique.append(path)
        paths_by_message[message_id] = tuple(unique)

    return AssetProjection(
        assets=assets,
        links=tuple(links),
        message_paths=MappingProxyType(paths_by_message),
    )
