"""Verify or locally restore the durable contents of an asset vault."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Sequence

from src.assets.models import AssetScope
from src.assets.vault import AssetVault


def _scopes(vault_root: Path) -> tuple[AssetScope, ...]:
    scopes_root = Path(vault_root) / "scopes"
    if not scopes_root.exists():
        return ()
    result = []
    for records in sorted(scopes_root.glob("*/*/records.jsonl")):
        source, account_key = records.parent.parent.name, records.parent.name
        result.append(AssetScope(source, None if account_key == "_legacy" else account_key))
    return tuple(result)


def verify_vault(vault_root: Path, *, plan: dict[str, object] | None = None) -> dict[str, object]:
    """Verify every committed scope and optionally compare plan totals."""
    vault_root = Path(vault_root)
    vault = AssetVault(vault_root)
    reports = [vault.verify(scope) for scope in _scopes(vault_root)]
    sources = sorted({report.scope.source for report in reports})
    if plan is not None:
        expected_sources = [str(entry["source"]) for entry in plan["sources"]]
        if sorted(expected_sources) != sources:
            raise ValueError("vault scope sources differ from migration plan")
    blob_paths = tuple((vault_root / "blobs" / "sha256").glob("*/*"))
    result = {
        "scope_count": len(reports),
        "capture_count": sum(report.capture_count for report in reports),
        "record_count": sum(report.record_count for report in reports),
        "referenced_blob_count": sum(report.blob_count for report in reports),
        "physical_blob_count": sum(path.is_file() for path in blob_paths),
        "sources": sources,
    }
    return result


def restore_vault(source_root: Path, destination_root: Path) -> dict[str, object]:
    """Copy only durable inputs into an empty root, then rebuild and verify state."""
    source_root = Path(source_root)
    destination_root = Path(destination_root)
    if destination_root.exists() and any(destination_root.iterdir()):
        raise ValueError("restore destination must be empty")
    destination_root.mkdir(parents=True, exist_ok=True)
    schema = source_root / "schema.json"
    if not schema.is_file():
        raise FileNotFoundError(schema)
    shutil.copy2(schema, destination_root / "schema.json")
    for path in sorted((source_root / "blobs" / "sha256").glob("*/*")):
        target = destination_root / path.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for path in sorted((source_root / "scopes").glob("*/*/records.jsonl")):
        target = destination_root / path.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    report = verify_vault(destination_root)
    for scope in _scopes(destination_root):
        if not AssetVault(destination_root).state_path(scope).is_file():
            raise RuntimeError(f"restore did not rebuild state for {scope.source}/{scope.account_key}")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--vault-root", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--vault-root", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify":
        report = verify_vault(args.vault_root)
    else:
        report = restore_vault(args.vault_root, args.destination)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
