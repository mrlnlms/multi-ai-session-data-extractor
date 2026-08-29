#!/usr/bin/env python3
"""Validate a reconciled data tree against source manifests and its ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def load_hashes(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            digest, item_path = line.rstrip("\n").split("  ", 1)
            records[item_path] = digest
    return records


def load_ledger(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree-root", type=Path, required=True)
    parser.add_argument("--local-sha", type=Path, required=True)
    parser.add_argument("--dvc-sha", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-prefix",
        action="append",
        default=[],
        help="Validate only paths equal to or below this prefix; repeatable.",
    )
    args = parser.parse_args()

    local = load_hashes(args.local_sha)
    dvc = load_hashes(args.dvc_sha)
    ledger = load_ledger(args.ledger)
    expected = dict(dvc)
    for row in ledger:
        if row["decision"].startswith("copy_"):
            expected[row["path"]] = local[row["path"]]
    if args.include_prefix:
        prefixes = tuple(prefix.rstrip("/") for prefix in args.include_prefix)
        expected = {
            item_path: value
            for item_path, value in expected.items()
            if any(item_path == prefix or item_path.startswith(f"{prefix}/") for prefix in prefixes)
        }

    actual_paths = {
        path.relative_to(args.tree_root).as_posix(): path
        for path in (args.tree_root / "data").rglob("*")
        if path.is_file()
    }
    if args.include_prefix:
        actual_paths = {
            item_path: path
            for item_path, path in actual_paths.items()
            if any(item_path == prefix or item_path.startswith(f"{prefix}/") for prefix in prefixes)
        }
    missing = sorted(expected.keys() - actual_paths.keys())
    unexpected = sorted(actual_paths.keys() - expected.keys())
    mismatched: list[str] = []
    for item_path, expected_digest in expected.items():
        path = actual_paths.get(item_path)
        if path is not None and digest(path) != expected_digest:
            mismatched.append(item_path)

    summary = {
        "expected_files": len(expected),
        "actual_files": len(actual_paths),
        "missing": missing,
        "unexpected": unexpected,
        "sha256_mismatches": mismatched,
        "valid": not missing and not unexpected and not mismatched,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
