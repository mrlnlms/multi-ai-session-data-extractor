"""Preview or materialize deterministic adoption of observable accounts."""

from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from src.account_catalog import (
    AccountCatalog,
    AccountCatalogRecord,
    LifecycleStatus,
    legacy_account_id,
    load_account_catalog,
)
from src.application.platforms import PlatformState, discover_platforms
from src.platforms.registry import KNOWN_PLATFORMS, PLATFORM_ACCOUNT_METADATA


def _classification_key(platform: str, technical_key: str) -> str:
    return f"{platform}:{technical_key}"


def build_catalog(
    states: Iterable[PlatformState],
    *,
    captured_at: datetime,
    classifications: Mapping[str, LifecycleStatus] | None = None,
) -> AccountCatalog:
    """Build a deterministic catalog or reject accounts needing a decision."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    explicit = dict(classifications or {})
    by_platform = {state.name: state for state in states}
    records: list[AccountCatalogRecord] = []
    unresolved: list[str] = []
    observed_keys: set[str] = set()

    for platform in KNOWN_PLATFORMS:
        metadata = PLATFORM_ACCOUNT_METADATA.get(platform)
        state = by_platform.get(platform)
        if metadata is None or state is None:
            continue
        for account in state.accounts:
            key = _classification_key(platform, account.key)
            observed_keys.add(key)
            lifecycle = explicit.get(key)
            if lifecycle is None and account.lifecycle_status is not None:
                lifecycle = account.lifecycle_status
            if lifecycle is None and account.key in metadata.fallback_keys:
                lifecycle = LifecycleStatus.ACTIVE
            if (
                lifecycle is None
                and account.key.startswith("archive:")
                and account.evidence.historical_present
            ):
                lifecycle = LifecycleStatus.HISTORICAL
            if lifecycle is None:
                unresolved.append(key)
                continue
            records.append(AccountCatalogRecord(
                account_id=account.account_id or legacy_account_id(platform, account.key),
                platform=platform,
                technical_key=account.key,
                lifecycle_status=lifecycle,
                created_at=captured_at,
                updated_at=captured_at,
            ))

    unknown = sorted(set(explicit) - observed_keys)
    if unknown:
        raise ValueError("Classifications do not match observable accounts: " + ", ".join(unknown))
    if unresolved:
        raise ValueError("Explicit lifecycle classification required for: " + ", ".join(unresolved))
    return AccountCatalog(records=tuple(records))


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def serialize_catalog(catalog: AccountCatalog) -> str:
    """Serialize a catalog reproducibly without machine-local metadata."""
    payload = {
        "version": catalog.version,
        "accounts": [
            {
                "account_id": record.account_id,
                "platform": record.platform,
                "technical_key": record.technical_key,
                "lifecycle_status": record.lifecycle_status.value,
                "created_at": _timestamp(record.created_at),
                "updated_at": _timestamp(record.updated_at),
            }
            for record in catalog.records
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
    except ValueError as exc:
        raise ValueError("--captured-at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--captured-at must be timezone-aware")
    return parsed


def _parse_classifications(values: Sequence[str]) -> dict[str, LifecycleStatus]:
    classifications: dict[str, LifecycleStatus] = {}
    for value in values:
        try:
            identity, raw_status = value.rsplit("=", 1)
            platform, technical_key = identity.split(":", 1)
            status = LifecycleStatus(raw_status)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "--classify must use Platform:key=active|disabled|historical"
            ) from exc
        if platform not in PLATFORM_ACCOUNT_METADATA or not technical_key:
            raise ValueError(f"Invalid account classification: {value}")
        if identity in classifications and classifications[identity] is not status:
            raise ValueError(f"Conflicting classifications for {identity}")
        classifications[identity] = status
    return classifications


def _write_catalog(path: Path, catalog: AccountCatalog, serialized: str) -> None:
    if path.exists():
        if load_account_catalog(path) == catalog:
            return
        raise ValueError(f"Refusing to overwrite different account catalog: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview deterministic adoption of the observable account inventory."
    )
    parser.add_argument(
        "--classify",
        action="append",
        default=[],
        metavar="PLATFORM:KEY=STATUS",
        help="explicitly classify a non-default account (repeatable)",
    )
    parser.add_argument(
        "--captured-at",
        type=str,
        help="timezone-aware ISO-8601 adoption timestamp (defaults to current UTC time)",
    )
    parser.add_argument(
        "--write",
        type=Path,
        metavar="PATH",
        help="atomically write the reviewed catalog instead of printing it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    captured_at = (
        _parse_timestamp(args.captured_at)
        if args.captured_at
        else datetime.now(timezone.utc)
    )
    catalog = build_catalog(
        discover_platforms(),
        captured_at=captured_at,
        classifications=_parse_classifications(args.classify),
    )
    serialized = serialize_catalog(catalog)
    if args.write is None:
        print(serialized, end="")
    else:
        _write_catalog(args.write, catalog, serialized)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
