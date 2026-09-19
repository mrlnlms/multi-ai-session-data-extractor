"""Value objects for the durable asset vault."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping, TypeAlias, cast


LogicalRecordType: TypeAlias = Literal[
    "capture", "delivery", "appearance", "blob", "observation"
]
RecordType: TypeAlias = Literal[
    "capture", "delivery", "appearance", "blob", "observation", "capture_commit"
]

_SCOPE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RECORD_TYPES = frozenset(
    {"capture", "delivery", "appearance", "blob", "observation", "capture_commit"}
)


def _validate_locator(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError(f"{name} must be a non-empty locator")
    if "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"{name} must not contain path separators")
    return value


def validate_digest(value: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    return value


@dataclass(frozen=True)
class AssetScope:
    """One independently locked source/account record stream."""

    source: str
    account_id: str | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.source, "source"),):
            if not isinstance(value, str) or _SCOPE_COMPONENT.fullmatch(value) is None:
                raise ValueError(f"{name} must be a safe path component")
        if self.account_id is not None and (
            not isinstance(self.account_id, str)
            or _SCOPE_COMPONENT.fullmatch(self.account_id) is None
        ):
            raise ValueError("account_id must be a safe path component or None")

    @property
    def account_key(self) -> str:
        return self.account_id if self.account_id is not None else "_legacy"

    def to_dict(self) -> dict[str, str | None]:
        return {"source": self.source, "account_id": self.account_id}


@dataclass(frozen=True)
class RecordEnvelope:
    """One complete, versioned record belonging to a capture transaction."""

    record_type: RecordType
    record_version: Literal[1]
    capture_id: str
    complete: Literal[True]
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if self.record_type not in _RECORD_TYPES:
            raise ValueError(f"unsupported record_type: {self.record_type!r}")
        if self.record_version != 1:
            raise ValueError("record_version must be 1")
        _validate_locator(self.capture_id, "capture_id")
        if self.complete is not True:
            raise ValueError("complete must be true")
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a dict")
        try:
            json.dumps(self.payload, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be finite JSON data") from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "record_type": self.record_type,
            "record_version": self.record_version,
            "capture_id": self.capture_id,
            "complete": self.complete,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, value: object) -> "RecordEnvelope":
        if not isinstance(value, dict) or set(value) != {
            "record_type", "record_version", "capture_id", "complete", "payload"
        }:
            raise ValueError("record envelope has unexpected fields")
        return cls(
            record_type=cast(RecordType, value["record_type"]),
            record_version=cast(Literal[1], value["record_version"]),
            capture_id=cast(str, value["capture_id"]),
            complete=cast(Literal[True], value["complete"]),
            payload=cast(dict[str, object], value["payload"]),
        )


@dataclass(frozen=True)
class CaptureBatch:
    """All logical records and new blob bytes for one atomic capture commit."""

    scope: AssetScope
    capture_id: str
    records: tuple[RecordEnvelope, ...]
    blobs: Mapping[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, AssetScope):
            raise TypeError("scope must be an AssetScope")
        _validate_locator(self.capture_id, "capture_id")
        records = tuple(self.records)
        if any(not isinstance(record, RecordEnvelope) for record in records):
            raise TypeError("records must contain RecordEnvelope values")
        if not records:
            raise ValueError("a capture batch must contain records")
        if any(record.capture_id != self.capture_id for record in records):
            raise ValueError("all records must belong to the batch capture_id")
        if any(record.record_type == "capture_commit" for record in records):
            raise ValueError("capture_commit is written by AssetVault")
        if sum(record.record_type == "capture" for record in records) != 1:
            raise ValueError("a capture batch must contain exactly one capture record")
        blobs = dict(self.blobs)
        for digest, payload in blobs.items():
            validate_digest(digest)
            if not isinstance(payload, bytes):
                raise TypeError("blob payloads must be bytes")
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError(f"blob payload does not match sha256 {digest}")
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "blobs", MappingProxyType(blobs))


@dataclass(frozen=True)
class AssetState:
    """Deterministic projection of all fully committed captures in one scope."""

    scope: AssetScope
    committed_captures: tuple[str, ...]
    records: tuple[RecordEnvelope, ...]
    log_size: int
    log_sha256: str

    @property
    def by_type(self) -> dict[str, tuple[RecordEnvelope, ...]]:
        return {
            record_type: tuple(
                record for record in self.records if record.record_type == record_type
            )
            for record_type in ("capture", "delivery", "appearance", "blob", "observation")
        }


@dataclass(frozen=True)
class VerificationReport:
    scope: AssetScope
    capture_count: int
    record_count: int
    blob_count: int
