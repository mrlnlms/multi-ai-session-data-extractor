"""Deterministic folding and serialization of committed asset records."""

from __future__ import annotations

import hashlib
import json

from .models import AssetScope, AssetState, RecordEnvelope


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def encode_envelope(record: RecordEnvelope) -> bytes:
    return canonical_json(record.to_dict()) + b"\n"


def capture_fingerprint(records: tuple[RecordEnvelope, ...]) -> str:
    payload = b"".join(encode_envelope(record) for record in records)
    return hashlib.sha256(payload).hexdigest()


def fold_committed_records(
    scope: AssetScope,
    captures: tuple[tuple[RecordEnvelope, ...], ...],
    committed_log: bytes,
) -> AssetState:
    records = tuple(record for capture in captures for record in capture)
    return AssetState(
        scope=scope,
        committed_captures=tuple(capture[0].capture_id for capture in captures),
        records=records,
        log_size=len(committed_log),
        log_sha256=hashlib.sha256(committed_log).hexdigest(),
    )

def state_to_dict(state: AssetState) -> dict[str, object]:
    return {
        "schema_version": 1,
        "scope": state.scope.to_dict(),
        "committed_captures": list(state.committed_captures),
        "records": [record.to_dict() for record in state.records],
        "log_size": state.log_size,
        "log_sha256": state.log_sha256,
    }


def encode_state(state: AssetState) -> bytes:
    return canonical_json(state_to_dict(state)) + b"\n"


def state_from_dict(value: object) -> AssetState:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "scope", "committed_captures", "records", "log_size", "log_sha256"
    }:
        raise ValueError("state snapshot has unexpected fields")
    if value["schema_version"] != 1:
        raise ValueError("unsupported state schema_version")
    raw_scope = value["scope"]
    if not isinstance(raw_scope, dict) or set(raw_scope) != {"source", "account_id"}:
        raise ValueError("state snapshot has invalid scope")
    captures = value["committed_captures"]
    records = value["records"]
    if not isinstance(captures, list) or not all(isinstance(item, str) for item in captures):
        raise ValueError("state snapshot has invalid committed_captures")
    if not isinstance(records, list):
        raise ValueError("state snapshot has invalid records")
    if not isinstance(value["log_size"], int) or value["log_size"] < 0:
        raise ValueError("state snapshot has invalid log_size")
    return AssetState(
        scope=AssetScope(raw_scope["source"], raw_scope["account_id"]),
        committed_captures=tuple(captures),
        records=tuple(RecordEnvelope.from_dict(record) for record in records),
        log_size=value["log_size"],
        log_sha256=str(value["log_sha256"]),
    )
