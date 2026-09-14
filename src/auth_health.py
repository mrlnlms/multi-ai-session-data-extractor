"""Strict machine-local observations from explicit authentication checks."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


HEALTH_VERSION = 1
DEFAULT_HEALTH_PATH = Path(".storage/account-health.json")


class AuthStatus(StrEnum):
    UNKNOWN = "unknown"
    MISSING = "missing"
    VALID = "valid"
    EXPIRED = "expired"
    ERROR = "error"


_SENSITIVE_DETAIL = re.compile(
    r"(?i)(https?://\S+|bearer\s+\S+|(?:cookie|token)\s*[=:]\s*\S+|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"
)


def sanitize_auth_detail(value: str) -> str:
    """Keep health diagnostics short and free of common secret/PII forms."""
    return _SENSITIVE_DETAIL.sub("[redacted]", value.replace("\n", " ")[:240])


@dataclass(frozen=True)
class AuthObservation:
    account_id: str
    status: AuthStatus
    checked_at: datetime | None
    detail: str


@dataclass(frozen=True)
class AuthHealth:
    version: int = HEALTH_VERSION
    records: tuple[AuthObservation, ...] = ()

    def get(self, account_id: str) -> AuthObservation | None:
        return next((item for item in self.records if item.account_id == account_id), None)


def _validate(observation: AuthObservation) -> None:
    try:
        uuid.UUID(observation.account_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("health account_id must be a valid UUID") from exc
    try:
        AuthStatus(observation.status)
    except ValueError as exc:
        raise ValueError(f"Unknown authentication status: {observation.status!r}") from exc
    if observation.checked_at is not None and (
        observation.checked_at.tzinfo is None or observation.checked_at.utcoffset() is None
    ):
        raise ValueError("health checked_at must be timezone-aware")
    if not isinstance(observation.detail, str):
        raise ValueError("health detail must be a string")


def load_auth_health(path: Path = DEFAULT_HEALTH_PATH) -> AuthHealth:
    if not path.exists():
        return AuthHealth()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid account health JSON: {path}") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"version", "observations"}:
        raise ValueError("Account health root fields must be version and observations")
    if type(raw["version"]) is not int or raw["version"] != HEALTH_VERSION:
        raise ValueError(f"Unsupported account health version: {raw['version']!r}")
    if not isinstance(raw["observations"], list):
        raise ValueError("Account health observations must be an array")
    records = []
    seen = set()
    for item in raw["observations"]:
        if not isinstance(item, Mapping) or set(item) != {"account_id", "status", "checked_at", "detail"}:
            raise ValueError("Account health fields must match version 1 exactly")
        checked = item["checked_at"]
        if checked is not None:
            if not isinstance(checked, str):
                raise ValueError("health checked_at must be an ISO-8601 string or null")
            try:
                checked = datetime.fromisoformat(checked.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("health checked_at must be a valid ISO-8601 timestamp") from exc
        try:
            status = AuthStatus(item["status"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unknown authentication status: {item['status']!r}") from exc
        record = AuthObservation(item["account_id"], status, checked, item["detail"])
        _validate(record)
        if record.account_id in seen:
            raise ValueError(f"Duplicate health account_id: {record.account_id}")
        records.append(record)
        seen.add(record.account_id)
    return AuthHealth(records=tuple(records))


def serialize_auth_health(health: AuthHealth) -> str:
    for item in health.records:
        _validate(item)
    payload = {"version": health.version, "observations": [
        {"account_id": item.account_id, "status": item.status.value,
         "checked_at": item.checked_at.isoformat().replace("+00:00", "Z") if item.checked_at else None,
         "detail": sanitize_auth_detail(item.detail)}
        for item in health.records
    ]}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def write_auth_health_atomic(path: Path, health: AuthHealth, *, expected_before: AuthHealth) -> None:
    if load_auth_health(path) != expected_before:
        raise ValueError(f"Refusing stale account health write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(serialize_auth_health(health), encoding="utf-8")
        if load_auth_health(path) != expected_before:
            raise ValueError(f"Refusing stale account health write: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def set_auth_observation(health: AuthHealth, observation: AuthObservation) -> AuthHealth:
    _validate(observation)
    return AuthHealth(records=tuple(
        item for item in health.records if item.account_id != observation.account_id
    ) + (observation,))
