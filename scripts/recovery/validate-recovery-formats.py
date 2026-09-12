#!/usr/bin/env python3
"""Validate JSON, JSONL, and Parquet container integrity in a data tree."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - supported for minimal recovery hosts
    pq = None


def area(path: Path, data_root: Path) -> str:
    parts = path.relative_to(data_root).parts
    return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    by_area: Counter[str] = Counter()
    errors: list[dict[str, object]] = []

    for path in sorted(args.data_root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        relative = path.relative_to(args.data_root).as_posix()
        by_area[area(path, args.data_root)] += 1
        try:
            if suffix == ".json":
                with path.open(encoding="utf-8") as handle:
                    json.load(handle)
                counts["json_valid"] += 1
            elif suffix == ".jsonl":
                with path.open(encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, 1):
                        if line.strip():
                            try:
                                json.loads(line)
                            except json.JSONDecodeError as exc:
                                raise ValueError(f"line {line_number}: {exc.msg}") from exc
                counts["jsonl_valid"] += 1
            elif suffix == ".parquet":
                size = path.stat().st_size
                with path.open("rb") as handle:
                    header = handle.read(4)
                    handle.seek(-4, 2)
                    footer = handle.read(4)
                if size < 12 or header != b"PAR1" or footer != b"PAR1":
                    raise ValueError("invalid Parquet magic bytes")
                counts["parquet_container_valid"] += 1
                if pq is not None:
                    parquet = pq.ParquetFile(path)
                    _ = parquet.schema_arrow
                    _ = parquet.metadata.num_rows
                    counts["parquet_metadata_valid"] += 1
            else:
                counts["other_files"] += 1
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            counts[f"{suffix or '<none>'}_invalid"] += 1
            errors.append({"path": relative, "error": str(exc)})

    summary = {
        "counts": dict(sorted(counts.items())),
        "files_by_area": dict(sorted(by_area.items())),
        "errors": errors,
        "valid": not errors,
        "note": (
            "Parquet container, metadata, and Arrow schemas validated."
            if pq is not None
            else "Parquet validation checks container magic only; schema validation requires pyarrow."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": summary["counts"], "errors": len(errors)}))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
