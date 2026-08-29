#!/usr/bin/env python3
"""Validate row counts and primary-key integrity of unified Parquets."""

from __future__ import annotations

import argparse
import json
import runpy
from pathlib import Path

import pyarrow.parquet as pq

TABLE_PKS = runpy.run_path(str(Path(__file__).with_name("unify-parquets.py")))["TABLE_PKS"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unified-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    tables: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    for table, primary_key in TABLE_PKS.items():
        path = args.unified_dir / f"{table}.parquet"
        if not path.exists():
            errors.append(f"missing table: {table}")
            continue
        arrow = pq.read_table(path)
        frame = arrow.to_pandas()
        missing_columns = [column for column in primary_key if column not in frame.columns]
        null_pk_rows = 0
        duplicate_pk_rows = 0
        if not missing_columns:
            null_pk_rows = int(frame[primary_key].isna().any(axis=1).sum())
            duplicate_pk_rows = int(frame.duplicated(subset=primary_key, keep=False).sum())
        if missing_columns or null_pk_rows or duplicate_pk_rows:
            errors.append(table)
        tables[table] = {
            "rows": len(frame),
            "columns": len(frame.columns),
            "primary_key": primary_key,
            "missing_primary_key_columns": missing_columns,
            "null_primary_key_rows": null_pk_rows,
            "duplicate_primary_key_rows": duplicate_pk_rows,
        }

    summary = {
        "tables": tables,
        "total_rows": sum(int(item["rows"]) for item in tables.values()),
        "errors": errors,
        "valid": not errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tables": len(tables), "total_rows": summary["total_rows"], "errors": errors}))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
