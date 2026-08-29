#!/usr/bin/env python3
"""Classify recovery differences without modifying either data tree.

The input is the ``divergent.tsv`` report produced by
``compare-recovery-manifests.py``. JSON comparisons distinguish formatting or
operational-marker changes from real payload changes. JSONL comparisons test
the append-only relationship expected from capture and reconciliation logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


OPERATIONAL_KEYS = {"_last_seen_in_server", "reconciled_at"}


def without_operational(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: without_operational(item)
            for key, item in value.items()
            if key not in OPERATIONAL_KEYS
        }
    if isinstance(value, list):
        return [without_operational(item) for item in value]
    return value


def differing_leaf_keys(left: Any, right: Any, result: Counter[str]) -> None:
    if type(left) is not type(right):
        result["<type>"] += 1
        return
    if isinstance(left, dict):
        for key in left.keys() | right.keys():
            if key not in left or key not in right:
                result[f"{key}:<presence>"] += 1
            else:
                differing_leaf_keys(left[key], right[key], result)
        return
    if isinstance(left, list):
        if len(left) != len(right):
            result["<list_length>"] += 1
            return
        for left_item, right_item in zip(left, right):
            differing_leaf_keys(left_item, right_item, result)
        return
    if left != right:
        result["<scalar>"] += 1


def classify_json(local_path: Path, dvc_path: Path) -> tuple[str, Counter[str]]:
    try:
        local = json.loads(local_path.read_text(encoding="utf-8"))
        dvc = json.loads(dvc_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "json_parse_error", Counter()
    if local == dvc:
        return "json_format_only", Counter()
    if without_operational(local) == without_operational(dvc):
        return "json_operational_only", Counter()
    leaves: Counter[str] = Counter()
    differing_leaf_keys(local, dvc, leaves)
    return "json_payload_change", leaves


def classify_jsonl(local_path: Path, dvc_path: Path) -> str:
    local = local_path.read_bytes().splitlines()
    dvc = dvc_path.read_bytes().splitlines()
    if local[: len(dvc)] == dvc:
        return "jsonl_dvc_prefix_of_local"
    if dvc[: len(local)] == local:
        return "jsonl_local_prefix_of_dvc"
    if set(dvc).issubset(set(local)):
        return "jsonl_dvc_subset_of_local"
    if set(local).issubset(set(dvc)):
        return "jsonl_local_subset_of_dvc"
    return "jsonl_overlap_or_conflict"


def load_paths(report: Path) -> list[str]:
    with report.open(encoding="utf-8", newline="") as handle:
        return [row["path"] for row in csv.DictReader(handle, delimiter="\t")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--dvc-root", type=Path, required=True)
    parser.add_argument("--divergent", type=Path, required=True)
    parser.add_argument("--local-only", type=Path)
    parser.add_argument("--dvc-only", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    classes: Counter[str] = Counter()
    payload_leaf_differences: Counter[str] = Counter()
    rows: list[tuple[str, str]] = []
    for item_path in load_paths(args.divergent):
        local_path = args.local_root / item_path
        dvc_path = args.dvc_root / item_path
        suffix = local_path.suffix.lower()
        if suffix == ".json":
            category, leaves = classify_json(local_path, dvc_path)
            payload_leaf_differences.update(leaves)
        elif suffix == ".jsonl":
            category = classify_jsonl(local_path, dvc_path)
        elif suffix == ".md":
            category = "generated_markdown"
        elif suffix == ".parquet":
            category = "derived_parquet"
        else:
            category = f"other:{suffix or '<none>'}"
        classes[category] += 1
        rows.append((item_path, category))

    normalized_pairs: list[dict[str, Any]] = []
    if args.local_only and args.dvc_only:
        local_only = load_paths(args.local_only)
        dvc_only = load_paths(args.dvc_only)
        dvc_by_nfc = {unicodedata.normalize("NFC", path): path for path in dvc_only}
        for local_item in local_only:
            dvc_item = dvc_by_nfc.get(unicodedata.normalize("NFC", local_item))
            if dvc_item:
                local_bytes = (args.local_root / local_item).read_bytes()
                dvc_bytes = (args.dvc_root / dvc_item).read_bytes()
                normalized_pairs.append(
                    {
                        "local_path": local_item,
                        "dvc_path": dvc_item,
                        "same_bytes": local_bytes == dvc_bytes,
                    }
                )

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "semantic-classes.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(("path", "semantic_class"))
        writer.writerows(rows)

    summary = {
        "counts": dict(sorted(classes.items())),
        "operational_keys_ignored": sorted(OPERATIONAL_KEYS),
        "payload_leaf_differences": payload_leaf_differences.most_common(),
        "unicode_normalization_pairs": normalized_pairs,
    }
    (args.output / "semantic-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
