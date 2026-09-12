#!/usr/bin/env python3
"""Overlay the newer local layer onto a prebuilt DVC baseline safely.

The destination must already be a separate copy of the restored DVC tree.
Only paths classified as local-only or divergent are considered. Finder
metadata and byte-identical Unicode filename aliases are skipped. Every copy
is verified against the expected local SHA-256 and recorded in a ledger.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import unicodedata
from pathlib import Path


def load_report(path: Path) -> list[dict[str, str]]:
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
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--local-only", type=Path, required=True)
    parser.add_argument("--dvc-only", type=Path, required=True)
    parser.add_argument("--divergent", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()

    if args.local_root.resolve() == args.destination_root.resolve():
        raise ValueError("source and destination must be different trees")
    if not (args.destination_root / "data").is_dir():
        raise FileNotFoundError("destination must contain the restored DVC data baseline")

    dvc_only = load_report(args.dvc_only)
    dvc_nfc = {
        unicodedata.normalize("NFC", row["path"]): row
        for row in dvc_only
    }
    decisions: list[tuple[str, str, str]] = []
    to_copy: list[dict[str, str]] = []

    for row in load_report(args.local_only):
        item_path = row["path"]
        if Path(item_path).name == ".DS_Store":
            decisions.append((item_path, "skip_finder_metadata", ""))
            continue
        alias = dvc_nfc.get(unicodedata.normalize("NFC", item_path))
        if alias and alias["dvc_sha256"] == row["local_sha256"]:
            decisions.append((item_path, "skip_identical_unicode_alias", alias["path"]))
            continue
        to_copy.append(row)
        decisions.append((item_path, "copy_local_only", ""))

    for row in load_report(args.divergent):
        to_copy.append(row)
        decisions.append((row["path"], "copy_newer_local_version", ""))

    for row in to_copy:
        item_path = row["path"]
        source = args.local_root / item_path
        destination = args.destination_root / item_path
        if not source.is_file():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        actual = digest(destination)
        if actual != row["local_sha256"]:
            raise ValueError(f"post-copy SHA-256 mismatch: {item_path}")

    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(("path", "decision", "related_path"))
        writer.writerows(decisions)

    copied = sum(decision.startswith("copy_") for _, decision, _ in decisions)
    skipped = len(decisions) - copied
    print(f"copied={copied} skipped={skipped} ledger={args.ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
