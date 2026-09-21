"""Explicit, read-only authentication checks routed by immutable account ID."""

from __future__ import annotations

import asyncio
import importlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.account_bindings import AccountBindings
from src.account_catalog import AccountCatalog, LifecycleStatus
from src.auth_health import AuthEvidenceMethod, AuthObservation, AuthStatus
from src.platforms.registry import PLATFORM_ACCOUNT_METADATA


@dataclass(frozen=True)
class ProbeResult:
    status: AuthStatus
    detail: str


_SENSITIVE = re.compile(
    r"(?i)(https?://\S+|bearer\s+\S+|cookie\s*[=:]\s*\S+|token\s*[=:]\s*\S+|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"
)


def redact_probe_detail(detail: object) -> str:
    text = str(detail).replace("\n", " ")[:240]
    return _SENSITIVE.sub("[redacted]", text)


def classify_probe_exception(exc: Exception) -> ProbeResult:
    detail = redact_probe_detail(exc)
    lowered = str(exc).lower()
    if any(marker in lowered for marker in ("http 401", "http 403", "unauthorized", "session_invalid", "not logged")):
        return ProbeResult(AuthStatus.EXPIRED, "Authentication rejected by the upstream read endpoint")
    return ProbeResult(AuthStatus.ERROR, detail or "Authentication probe failed")


def check_account_auth(
    account_id: str,
    *,
    catalog: AccountCatalog,
    bindings: AccountBindings,
    storage_root: Path = Path(".storage"),
) -> AuthObservation:
    record = next((item for item in catalog.records if item.account_id == account_id), None)
    if record is None:
        raise ValueError(f"Unknown account_id: {account_id}")
    if record.lifecycle_status is LifecycleStatus.HISTORICAL:
        raise ValueError("Historical archive accounts cannot be authentication-probed")
    binding = bindings.get(account_id)
    if binding is None:
        return AuthObservation(account_id, AuthStatus.MISSING, None, "No local profile binding")
    metadata = PLATFORM_ACCOUNT_METADATA[record.platform]
    profile = storage_root / f"{metadata.profile_prefix}{binding.profile_key}"
    if record.platform == "Perplexity" and binding.profile_key == "default":
        legacy = storage_root / "perplexity-profile"
        if legacy.is_dir():
            profile = legacy
    if not profile.is_dir():
        return AuthObservation(account_id, AuthStatus.MISSING, None, "Bound profile is missing")
    source = metadata.registry_key
    module = importlib.import_module(f"src.platforms.{source}.probes.auth_health")
    try:
        result = asyncio.run(module.probe(binding.profile_key))
    except Exception as exc:  # adapters also classify; defense at the boundary
        result = classify_probe_exception(exc)
    if not isinstance(result, ProbeResult):
        result = ProbeResult(AuthStatus.ERROR, "Invalid platform probe result")
    checked_at = datetime.now(timezone.utc) if result.status is not AuthStatus.UNKNOWN else None
    method = AuthEvidenceMethod.PROBE if checked_at is not None else None
    return AuthObservation(account_id, result.status, checked_at, redact_probe_detail(result.detail), method)
