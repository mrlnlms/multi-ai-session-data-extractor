#!/usr/bin/env python3
"""Compare recovery manifests without touching source data.

Input SHA-256 manifests use the ``shasum -a 256`` format. Size manifests
use the macOS ``stat -f '%z\\t%N'`` format, whose separator is the literal
two-character sequence ``\\t``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load_hashes(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            try:
                digest, item_path = line.split("  ", 1)
            except ValueError as exc:
                raise ValueError(f"invalid SHA manifest line {path}:{number}") from exc
            records[item_path] = digest
    return records


def load_sizes(path: Path) -> dict[str, int]:
    records: dict[str, int] = {}
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            try:
                size, item_path = line.split("\\t", 1)
            except ValueError as exc:
                raise ValueError(f"invalid size manifest line {path}:{number}") from exc
            records[item_path] = int(size)
    return records


def area_for(item_path: str) -> str:
    parts = Path(item_path).parts
    if len(parts) >= 3 and parts[0] == "data":
        return "/".join(parts[:3])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return item_path


def write_rows(path: Path, rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("path\tlocal_size\tdvc_size\tlocal_sha256\tdvc_sha256\n")
        for row in rows:
            handle.write("\t".join("" if value is None else str(value) for value in row))
            handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-sha", type=Path, required=True)
    parser.add_argument("--local-sizes", type=Path, required=True)
    parser.add_argument("--dvc-sha", type=Path, required=True)
    parser.add_argument("--dvc-sizes", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    local_hashes = load_hashes(args.local_sha)
    local_sizes = load_sizes(args.local_sizes)
    dvc_hashes = load_hashes(args.dvc_sha)
    dvc_sizes = load_sizes(args.dvc_sizes)

    if local_hashes.keys() != local_sizes.keys():
        raise ValueError("local hash and size manifests have different paths")
    if dvc_hashes.keys() != dvc_sizes.keys():
        raise ValueError("DVC hash and size manifests have different paths")

    classes: dict[str, list[tuple]] = {
        "identical": [],
        "local_only": [],
        "dvc_only": [],
        "divergent": [],
    }
    by_area: dict[str, Counter] = {}

    for item_path in sorted(local_hashes.keys() | dvc_hashes.keys()):
        local_hash = local_hashes.get(item_path)
        dvc_hash = dvc_hashes.get(item_path)
        row = (
            item_path,
            local_sizes.get(item_path),
            dvc_sizes.get(item_path),
            local_hash,
            dvc_hash,
        )
        if local_hash is None:
            category = "dvc_only"
        elif dvc_hash is None:
            category = "local_only"
        elif local_hash == dvc_hash:
            category = "identical"
        else:
            category = "divergent"
        classes[category].append(row)
        by_area.setdefault(area_for(item_path), Counter())[category] += 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for category, rows in classes.items():
        write_rows(args.output_dir / f"{category}.tsv", rows)

    summary = {
        "local_files": len(local_hashes),
        "dvc_files": len(dvc_hashes),
        "union_files": len(local_hashes.keys() | dvc_hashes.keys()),
        "counts": {category: len(rows) for category, rows in classes.items()},
        "bytes": {
            "local": sum(local_sizes.values()),
            "dvc": sum(dvc_sizes.values()),
            "local_only": sum(row[1] or 0 for row in classes["local_only"]),
            "dvc_only": sum(row[2] or 0 for row in classes["dvc_only"]),
            "divergent_local": sum(row[1] or 0 for row in classes["divergent"]),
            "divergent_dvc": sum(row[2] or 0 for row in classes["divergent"]),
        },
        "by_area": {
            area: dict(sorted(counts.items()))
            for area, counts in sorted(by_area.items())
        },
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary["counts"], sort_keys=True))
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
