"""Strict machine-local mapping from immutable account IDs to profile keys."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.account_catalog import validate_technical_key


BINDINGS_VERSION = 1
DEFAULT_BINDINGS_PATH = Path(".storage/account-bindings.json")


@dataclass(frozen=True)
class AccountBinding:
    account_id: str
    profile_key: str
    updated_at: datetime


@dataclass(frozen=True)
class AccountBindings:
    version: int = BINDINGS_VERSION
    records: tuple[AccountBinding, ...] = ()

    def get(self, account_id: str) -> AccountBinding | None:
        return next((item for item in self.records if item.account_id == account_id), None)


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("binding account_id must be a UUID string")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError("binding account_id must be a valid UUID") from exc


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("binding updated_at must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("binding updated_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("binding updated_at must be timezone-aware")
    return parsed


def load_account_bindings(path: Path = DEFAULT_BINDINGS_PATH) -> AccountBindings:
    if not path.exists():
        return AccountBindings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid account bindings JSON: {path}") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"version", "bindings"}:
        raise ValueError("Account bindings root fields must be version and bindings")
    if type(raw["version"]) is not int or raw["version"] != BINDINGS_VERSION:
        raise ValueError(f"Unsupported account bindings version: {raw['version']!r}")
    if not isinstance(raw["bindings"], list):
        raise ValueError("Account bindings must be an array")
    records = []
    seen = set()
    for item in raw["bindings"]:
        if not isinstance(item, Mapping) or set(item) != {"account_id", "profile_key", "updated_at"}:
            raise ValueError("Account binding fields must match version 1 exactly")
        account_id = _uuid(item["account_id"])
        if account_id in seen:
            raise ValueError(f"Duplicate binding account_id: {account_id}")
        profile_key = validate_technical_key(item["profile_key"], allow_archive=False)
        records.append(AccountBinding(account_id, profile_key, _timestamp(item["updated_at"])))
        seen.add(account_id)
    return AccountBindings(records=tuple(records))


def serialize_account_bindings(bindings: AccountBindings) -> str:
    payload = {"version": bindings.version, "bindings": [
        {"account_id": item.account_id, "profile_key": item.profile_key,
         "updated_at": item.updated_at.isoformat().replace("+00:00", "Z")}
        for item in bindings.records
    ]}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def write_account_bindings_atomic(path: Path, bindings: AccountBindings, *, expected_before: AccountBindings) -> None:
    if load_account_bindings(path) != expected_before:
        raise ValueError(f"Refusing stale account bindings write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(serialize_account_bindings(bindings), encoding="utf-8")
        if load_account_bindings(path) != expected_before:
            raise ValueError(f"Refusing stale account bindings write: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def set_account_binding(bindings: AccountBindings, binding: AccountBinding) -> AccountBindings:
    _uuid(binding.account_id)
    validate_technical_key(binding.profile_key, allow_archive=False)
    if binding.updated_at.tzinfo is None or binding.updated_at.utcoffset() is None:
        raise ValueError("binding updated_at must be timezone-aware")
    return AccountBindings(records=tuple(
        item for item in bindings.records if item.account_id != binding.account_id
    ) + (binding,))
