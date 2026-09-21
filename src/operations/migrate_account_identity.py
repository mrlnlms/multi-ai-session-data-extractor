"""Preview-first migration from technical account paths to UUID paths."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.account_catalog import (
    AccountCatalog, AccountCatalogRecord, load_account_catalog,
    write_account_catalog_atomic,
)
from src.accounts import DEFAULT_ACCOUNTS_FILE, load_account_registry
from src.platforms.registry import PLATFORM_ACCOUNT_METADATA


@dataclass(frozen=True)
class PathMove:
    source: Path
    destination: Path


@dataclass(frozen=True)
class ArchiveMetadata:
    directory: Path
    archive_key: str


@dataclass(frozen=True)
class AccountIdentityMigrationPlan:
    before: AccountCatalog
    after: AccountCatalog
    moves: tuple[PathMove, ...]
    archive_metadata: tuple[ArchiveMetadata, ...] = ()


def uuid_account_dir(base: Path, account_id: str) -> Path:
    return base / f"account-{account_id}"


def _legacy_account_dir(base: Path, technical_key: str) -> Path:
    if technical_key == "default":
        return base
    suffix = technical_key if technical_key.startswith("account-") else f"account-{technical_key}"
    return base / suffix


def _default_root_moves(base: Path, destination: Path) -> list[PathMove]:
    if not base.is_dir():
        return []
    moves = []
    for child in sorted(base.iterdir(), key=lambda path: path.name):
        if child.name.startswith("account-"):
            continue
        moves.append(PathMove(child, destination / child.name))
    return moves


def _historical_key(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"archive:{normalized}"


def _presentation_metadata(
    platform: str,
    technical_key: str,
    registry: dict[str, dict[str, str]],
) -> tuple[str | None, str | None]:
    metadata = PLATFORM_ACCOUNT_METADATA[platform]
    entries = registry.get(metadata.registry_key, {})
    email = entries.get(technical_key) or entries.get(f"account-{technical_key}")
    return None, email


def plan_migration(
    *,
    catalog_path: Path,
    raw_root: Path,
    merged_root: Path,
    external_root: Path,
    registry_path: Path = DEFAULT_ACCOUNTS_FILE,
) -> AccountIdentityMigrationPlan:
    before = load_account_catalog(catalog_path)
    if not before.requires_identity_migration:
        raise ValueError("Account catalog is already version 2; no identity migration is needed")
    registry = load_account_registry(registry_path)
    records: list[AccountCatalogRecord] = []
    moves: list[PathMove] = []
    archive_metadata: list[ArchiveMetadata] = []
    for record in before.records:
        technical_key = before.legacy_technical_key(record.account_id)
        if technical_key is None:
            raise ValueError(f"Missing legacy locator for account_id: {record.account_id}")
        display_name, email = _presentation_metadata(record.platform, technical_key, registry)
        records.append(AccountCatalogRecord(
            account_id=record.account_id,
            platform=record.platform,
            display_name=display_name,
            email=email,
            lifecycle_status=record.lifecycle_status,
            created_at=record.created_at,
            updated_at=record.updated_at,
        ))
        if technical_key.startswith("archive:"):
            archive_name = PLATFORM_ACCOUNT_METADATA[record.platform].historical_archive_root
            if archive_name:
                archive_root = external_root / archive_name
                source = next(
                    (path for path in sorted(archive_root.iterdir())
                     if path.is_dir() and _historical_key(path.name) == technical_key),
                    None,
                ) if archive_root.is_dir() else None
                if source is not None:
                    destination = uuid_account_dir(archive_root, record.account_id)
                    moves.append(PathMove(source, destination))
                    archive_metadata.append(ArchiveMetadata(
                        destination,
                        technical_key.removeprefix("archive:"),
                    ))
            continue
        for root in (raw_root, merged_root):
            base = root / record.platform
            destination = uuid_account_dir(base, record.account_id)
            if technical_key == "default":
                moves.extend(_default_root_moves(base, destination))
            else:
                source = _legacy_account_dir(base, technical_key)
                if source.exists():
                    moves.append(PathMove(source, destination))
    destinations: set[Path] = set()
    for move in moves:
        if move.destination in destinations:
            raise ValueError(f"Multiple legacy paths target {move.destination}")
        destinations.add(move.destination)
        if move.destination.exists():
            raise ValueError(f"Migration destination already exists: {move.destination}")
    after = AccountCatalog(records=tuple(records))
    return AccountIdentityMigrationPlan(
        before, after, tuple(moves), tuple(archive_metadata),
    )


def apply_migration(plan: AccountIdentityMigrationPlan, *, catalog_path: Path) -> None:
    completed: list[PathMove] = []
    written_metadata: list[Path] = []
    created_parents: set[Path] = set()
    try:
        for move in plan.moves:
            if not move.source.exists():
                raise ValueError(f"Migration source disappeared: {move.source}")
            if move.destination.exists():
                raise ValueError(f"Migration destination appeared: {move.destination}")
            if not move.destination.parent.exists():
                move.destination.parent.mkdir(parents=True)
                created_parents.add(move.destination.parent)
            os.replace(move.source, move.destination)
            completed.append(move)
        for metadata in plan.archive_metadata:
            metadata_path = metadata.directory / "archive_metadata.json"
            if metadata_path.exists():
                raise ValueError(f"Archive metadata already exists: {metadata_path}")
            metadata_path.write_text(
                json.dumps({"archive_key": metadata.archive_key}, indent=2) + "\n",
                encoding="utf-8",
            )
            written_metadata.append(metadata_path)
        write_account_catalog_atomic(catalog_path, plan.after, expected_before=plan.before)
    except Exception:
        for metadata_path in written_metadata:
            metadata_path.unlink(missing_ok=True)
        for move in reversed(completed):
            if move.destination.exists() and not move.source.exists():
                move.source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(move.destination, move.source)
        for parent in sorted(created_parents, key=lambda path: len(path.parts), reverse=True):
            try:
                parent.rmdir()
            except OSError:
                pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply the one-time account identity/path migration.",
    )
    parser.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"))
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--merged-root", type=Path, default=Path("data/merged"))
    parser.add_argument("--external-root", type=Path, default=Path("data/external"))
    parser.add_argument("--registry-path", type=Path, default=DEFAULT_ACCOUNTS_FILE)
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    plan = plan_migration(
        catalog_path=args.catalog_path,
        raw_root=args.raw_root,
        merged_root=args.merged_root,
        external_root=args.external_root,
        registry_path=args.registry_path,
    )
    print(f"Catalog: version 1 -> version 2 ({len(plan.after.records)} UUIDs preserved)")
    for move in plan.moves:
        print(f"MOVE {move.source} -> {move.destination}")
    for metadata in plan.archive_metadata:
        print(f"WRITE {metadata.directory / 'archive_metadata.json'}")
    if not args.apply:
        print("Preview only; pass --apply to move paths and replace the catalog.")
        return 0
    apply_migration(plan, catalog_path=args.catalog_path)
    print("Applied locally. DVC/Git publication was not run.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
