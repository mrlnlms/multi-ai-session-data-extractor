"""Incremental capture writer shared by web asset downloaders."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .models import AssetScope, CaptureBatch, RecordEnvelope
from .state import canonical_json
from .vault import AssetVault


ObservationStatus = Literal["available", "reference_only"]
DEFAULT_MAX_BATCH_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class AssetObservation:
    """One asset reference observed by a downloader in the current capture."""

    delivery_id: str
    object_id: str
    representation_kind: str
    payload: bytes | None = None
    file_name: str | None = None
    mime_type: str | None = None
    upstream_locator: str | None = None
    metadata_json: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("delivery_id", "object_id", "representation_kind"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if self.payload is not None and not isinstance(self.payload, bytes):
            raise TypeError("payload must be bytes or None")


class WebAssetCaptureSession:
    """Bound memory while committing one downloader's observed asset stream."""

    def __init__(
        self,
        asset_vault: AssetVault | None,
        *,
        source: str,
        account_id: str | None,
        evidence_path: Path,
        capture_method: str,
        staging_root: Path | None = None,
        max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES,
    ) -> None:
        if not isinstance(max_batch_bytes, int) or max_batch_bytes <= 0:
            raise ValueError("max_batch_bytes must be a positive integer")
        self.asset_vault = asset_vault
        self.source = source
        self.account_id = account_id
        self.evidence_path = Path(evidence_path)
        self.capture_method = capture_method
        self.staging_root = Path(staging_root) if staging_root is not None else None
        self.max_batch_bytes = max_batch_bytes
        self._pending: dict[str, AssetObservation] = {}
        self._pending_bytes = 0
        self._observed_ids: set[str] = set()

    def observe(self, observation: AssetObservation) -> None:
        self._observed_ids.add(observation.delivery_id)
        if self.asset_vault is None:
            return
        size = len(observation.payload) if observation.payload is not None else 0
        previous = self._pending.get(observation.delivery_id)
        if previous is not None:
            previous_size = len(previous.payload) if previous.payload is not None else 0
            if previous.payload is not None and observation.payload is None:
                return
            if previous.payload is not None and observation.payload is not None:
                if hashlib.sha256(previous.payload).digest() != hashlib.sha256(
                    observation.payload
                ).digest():
                    raise ValueError(
                        f"delivery {observation.delivery_id!r} changed immutable bytes"
                    )
                return
            self._pending_bytes -= previous_size
        if self._pending and self._pending_bytes + size > self.max_batch_bytes:
            self._flush()
        self._pending[observation.delivery_id] = observation
        self._pending_bytes += size
        if self._pending_bytes >= self.max_batch_bytes:
            self._flush()

    def finish(self, *, complete_discovery: bool) -> None:
        if self.asset_vault is None:
            return
        self._flush()
        _commit_web_asset_discovery(
            self.asset_vault,
            source=self.source,
            account_id=self.account_id,
            observed_delivery_ids=frozenset(self._observed_ids),
            complete_discovery=complete_discovery,
            evidence_path=self.evidence_path,
            capture_method=f"{self.capture_method}:discovery",
        )
        self._retire_committed_staging_files()

    def _retire_committed_staging_files(self) -> None:
        """Remove vault-backed compatibility bytes after a durable commit."""
        if self.asset_vault is None or self.staging_root is None:
            return
        root = self.staging_root
        if not root.is_dir() or root.is_symlink():
            return
        state = self.asset_vault.load_state(AssetScope(self.source, self.account_id))
        committed = {
            str(record.payload["sha256"])
            for record in state.records
            if record.record_type == "blob" and isinstance(record.payload.get("sha256"), str)
        }
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_symlink():
                continue
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
                continue
            if not path.is_file():
                continue
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest not in committed:
                continue
            # read_blob verifies that the authoritative copy is present and intact.
            if self.asset_vault.read_blob(digest) == payload:
                path.unlink()

    def _flush(self) -> None:
        if not self._pending:
            return
        commit_web_asset_capture(
            self.asset_vault,
            source=self.source,
            account_id=self.account_id,
            observations=tuple(self._pending.values()),
            complete_discovery=False,
            evidence_path=self.evidence_path,
            capture_method=self.capture_method,
        )
        self._pending.clear()
        self._pending_bytes = 0


def _record(
    record_type: str, capture_id: str, payload: dict[str, object]
) -> RecordEnvelope:
    return RecordEnvelope(record_type, 1, capture_id, True, payload)  # type: ignore[arg-type]


def _known_deliveries(vault: AssetVault, scope: AssetScope) -> dict[str, dict[str, object]]:
    known: dict[str, dict[str, object]] = {}
    state = vault.load_state(scope)
    for record in state.records:
        if record.record_type != "delivery":
            continue
        delivery_id = record.payload.get("delivery_id")
        if not isinstance(delivery_id, str) or not delivery_id:
            raise ValueError("delivery record has no valid delivery_id")
        previous = known.get(delivery_id)
        if previous is not None and previous != record.payload:
            raise ValueError(f"conflicting delivery record: {delivery_id}")
        known.setdefault(delivery_id, dict(record.payload))
    for record in state.records:
        if record.record_type != "observation":
            continue
        delivery_id = record.payload.get("delivery_id")
        current = known.get(delivery_id) if isinstance(delivery_id, str) else None
        if current is None or record.payload.get("status") != "available":
            continue
        current["availability"] = "available"
        digest = record.payload.get("sha256")
        if isinstance(digest, str):
            current["sha256"] = digest
            current["size_bytes"] = record.payload.get("size_bytes")
    return known


def _commit_web_asset_discovery(
    asset_vault: AssetVault,
    *,
    source: str,
    account_id: str | None,
    observed_delivery_ids: frozenset[str],
    complete_discovery: bool,
    evidence_path: Path,
    capture_method: str,
) -> str:
    scope = AssetScope(source, account_id)
    known = _known_deliveries(asset_vault, scope)
    missing = sorted(set(known) - observed_delivery_ids) if complete_discovery else []
    fingerprint = {
        "source": source,
        "account_id": account_id,
        "capture_method": capture_method,
        "complete_discovery": complete_discovery,
        "evidence_path": str(evidence_path),
        "observed_delivery_ids": sorted(observed_delivery_ids),
        "preserved_missing": missing,
    }
    capture_id = "web-discovery-" + hashlib.sha256(canonical_json(fingerprint)).hexdigest()
    if capture_id in asset_vault.load_state(scope).committed_captures:
        return capture_id
    records = [
        _record(
            "capture",
            capture_id,
            {
                "source": source,
                "account_id": account_id,
                "capture_method": capture_method,
                "complete_discovery": complete_discovery,
                "evidence_path": str(evidence_path),
            },
        )
    ]
    records.extend(
        _record(
            "observation",
            capture_id,
            {
                "observation_id": f"{capture_id}:{delivery_id}",
                "delivery_id": delivery_id,
                "status": "preserved_missing",
                "observed_status": "not_discovered",
            },
        )
        for delivery_id in missing
    )
    asset_vault.commit(CaptureBatch(scope, capture_id, tuple(records)))
    return capture_id


def commit_web_asset_capture(
    asset_vault: AssetVault | None,
    *,
    source: str,
    account_id: str | None,
    observations: tuple[AssetObservation, ...],
    complete_discovery: bool,
    evidence_path: Path,
    capture_method: str = "web_asset_download",
) -> str | None:
    """Commit a downloader pass, or do nothing while legacy mode is selected.

    Delivery identity is immutable. Later download success enriches a prior
    reference through an observation and blob record; an HTTP failure records
    the failed attempt but retains an already available delivery as available.
    Complete discovery may mark known, unseen deliveries ``preserved_missing``;
    partial discovery never changes unseen deliveries.
    """

    if asset_vault is None:
        return None
    scope = AssetScope(source, account_id)
    known = _known_deliveries(asset_vault, scope)
    observed: dict[str, AssetObservation] = {}
    for item in observations:
        previous = observed.get(item.delivery_id)
        if previous is not None and previous != item:
            raise ValueError(f"conflicting current observation: {item.delivery_id}")
        observed[item.delivery_id] = item

    normalized: list[dict[str, object]] = []
    for delivery_id in sorted(observed):
        item = observed[delivery_id]
        digest = hashlib.sha256(item.payload).hexdigest() if item.payload is not None else None
        prior = known.get(delivery_id)
        prior_available = prior is not None and prior.get("availability") == "available"
        effective_status: ObservationStatus = (
            "available" if item.payload is not None or prior_available else "reference_only"
        )
        normalized.append(
            {
                "delivery_id": delivery_id,
                "object_id": item.object_id,
                "representation_kind": item.representation_kind,
                "file_name": item.file_name,
                "mime_type": item.mime_type,
                "upstream_locator": item.upstream_locator,
                "metadata_json": item.metadata_json,
                "sha256": digest,
                "size_bytes": len(item.payload) if item.payload is not None else None,
                "observed_status": "available" if item.payload is not None else "reference_only",
                "effective_status": effective_status,
                "failure_reason": item.failure_reason,
            }
        )

    missing = sorted(set(known) - set(observed)) if complete_discovery else []
    fingerprint = {
        "source": source,
        "account_id": account_id,
        "capture_method": capture_method,
        "complete_discovery": complete_discovery,
        "evidence_path": str(Path(evidence_path)),
        "observations": normalized,
        "preserved_missing": missing,
    }
    capture_id = "web-" + hashlib.sha256(canonical_json(fingerprint)).hexdigest()
    if capture_id in asset_vault.load_state(scope).committed_captures:
        return capture_id
    records: list[RecordEnvelope] = [
        _record(
            "capture",
            capture_id,
            {
                "source": source,
                "account_id": account_id,
                "capture_method": capture_method,
                "complete_discovery": complete_discovery,
                "evidence_path": str(Path(evidence_path)),
            },
        )
    ]
    blobs: dict[str, bytes] = {}
    blob_rows: set[str] = set()
    for row in normalized:
        delivery_id = str(row["delivery_id"])
        item = observed[delivery_id]
        prior = known.get(delivery_id)
        if prior is None:
            records.append(
                _record(
                    "delivery",
                    capture_id,
                    {
                        "delivery_id": delivery_id,
                        "object_id": row["object_id"],
                        "representation_kind": row["representation_kind"],
                        "file_name": row["file_name"],
                        "mime_type": row["mime_type"],
                        "size_bytes": row["size_bytes"],
                        "sha256": row["sha256"],
                        "availability": row["effective_status"],
                        "metadata_json": row["metadata_json"],
                        "is_preserved_missing": False,
                    },
                )
            )
        digest = row["sha256"]
        if isinstance(digest, str) and item.payload is not None:
            prior_digest = prior.get("sha256") if prior is not None else None
            if prior_digest is not None and prior_digest != digest:
                raise ValueError(f"delivery {delivery_id!r} changed immutable bytes")
            blobs[digest] = item.payload
            if digest not in blob_rows:
                records.append(
                    _record(
                        "blob",
                        capture_id,
                        {
                            "sha256": digest,
                            "size_bytes": len(item.payload),
                            "mime_type": row["mime_type"],
                        },
                    )
                )
                blob_rows.add(digest)
        observation_payload = {
            "observation_id": f"{capture_id}:{delivery_id}",
            "delivery_id": delivery_id,
            "status": row["effective_status"],
            "observed_status": row["observed_status"],
            "failure_reason": row["failure_reason"],
            "upstream_locator": row["upstream_locator"],
        }
        if isinstance(digest, str):
            observation_payload["sha256"] = digest
            observation_payload["size_bytes"] = row["size_bytes"]
        records.append(_record("observation", capture_id, observation_payload))

    for delivery_id in missing:
        records.append(
            _record(
                "observation",
                capture_id,
                {
                    "observation_id": f"{capture_id}:{delivery_id}",
                    "delivery_id": delivery_id,
                    "status": "preserved_missing",
                    "observed_status": "not_discovered",
                },
            )
        )

    asset_vault.commit(
        CaptureBatch(
            scope=scope,
            capture_id=capture_id,
            records=tuple(records),
            blobs=blobs,
        )
    )
    return capture_id
