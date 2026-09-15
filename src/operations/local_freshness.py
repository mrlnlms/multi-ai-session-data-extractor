"""Read-only, local file-metadata freshness check for new agent sessions.

This is not a content hash or a DVC remote/publication check. It reports whether
the current local parser inputs, processed tables, and unified tables have an
observable output at least as recent as their local input files.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.application.platforms import (
    DEFAULT_PARSER_INPUT_SUFFIXES,
    PARSER_INPUT_SUFFIXES,
)
from src.platforms.registry import KNOWN_PLATFORMS
from src.runtime.project import find_project_root
from src.workflows.unify import discover_parquets


@dataclass(frozen=True)
class FreshnessReport:
    status: str
    checked_sources: int
    checked_tables: int
    stale_sources: tuple[str, ...]
    stale_tables: tuple[str, ...]
    missing_sources: tuple[str, ...]
    missing_tables: tuple[str, ...]
    newest_input_ns: int | None
    newest_output_ns: int | None

    def compact(self) -> str:
        def names(values: tuple[str, ...]) -> str:
            return ", ".join(values[:4]) + (f" +{len(values) - 4}" if len(values) > 4 else "")

        details = []
        if self.stale_sources:
            details.append(f"source stale: {names(self.stale_sources)}")
        if self.stale_tables:
            details.append(f"unified stale: {names(self.stale_tables)}")
        if self.missing_sources:
            details.append(f"source missing: {names(self.missing_sources)}")
        if self.missing_tables:
            details.append(f"unified missing: {names(self.missing_tables)}")
        detail = "; ".join(details) if details else "no local timestamp gap"
        return (
            f"Local archive metadata: {self.status}; checked {self.checked_sources} "
            f"sources and {self.checked_tables} unified tables; {detail}. "
            "Not a DVC remote or content-integrity check."
        )


def _newest(paths: list[Path]) -> int | None:
    return max((path.stat().st_mtime_ns for path in paths), default=None)


def _parser_inputs(data_root: Path, platform: str) -> list[Path]:
    suffixes = PARSER_INPUT_SUFFIXES.get(platform, DEFAULT_PARSER_INPUT_SUFFIXES)
    merged = data_root / "merged" / platform
    raw = data_root / "raw" / platform
    root = merged if merged.is_dir() else raw
    if not root.is_dir():
        return []
    files = [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
        and path.name not in {"capture_log.jsonl", "reconcile_log.jsonl"}
    ]
    if platform == "NotebookLM":
        historical = data_root / "external" / "notebooklm-snapshots"
        if historical.is_dir():
            files.extend(path for path in historical.rglob("*.json") if path.is_file())
    return files


def inspect_archive(
    root: Path, *, platforms: tuple[str, ...] | None = None,
) -> FreshnessReport:
    """Inspect local file timestamps without writing data or querying DVC."""
    data_root = root / "data"
    names = platforms if platforms is not None else tuple(KNOWN_PLATFORMS)
    stale_sources: list[str] = []
    missing_sources: list[str] = []
    checked_sources = 0
    all_inputs: list[int] = []
    all_outputs: list[int] = []

    for platform in names:
        inputs = _parser_inputs(data_root, platform)
        processed = data_root / "processed" / platform
        outputs = (
            sorted(path for path in processed.glob("*.parquet") if "_manual_" not in path.stem)
            if processed.is_dir() else []
        )
        input_ns = _newest(inputs)
        output_ns = min((path.stat().st_mtime_ns for path in outputs), default=None)
        if input_ns is None or output_ns is None:
            missing_sources.append(platform)
            continue
        checked_sources += 1
        all_inputs.append(input_ns)
        all_outputs.extend(path.stat().st_mtime_ns for path in outputs)
        if output_ns < input_ns:
            stale_sources.append(platform)

    by_table = (
        discover_parquets(data_root / "processed")
        if (data_root / "processed").is_dir() else {}
    )
    unified = data_root / "unified"
    stale_tables: list[str] = []
    missing_tables: list[str] = []
    checked_tables = 0
    for table, inputs in by_table.items():
        if not inputs:
            continue
        output = unified / f"{table}.parquet"
        if not output.is_file():
            missing_tables.append(table)
            continue
        checked_tables += 1
        output_ns = output.stat().st_mtime_ns
        all_outputs.append(output_ns)
        if output_ns < _newest(inputs):
            stale_tables.append(table)

    status = (
        "stale" if stale_sources or stale_tables else
        "incomplete" if missing_sources or missing_tables or checked_tables == 0 else
        "current"
    )
    return FreshnessReport(
        status=status,
        checked_sources=checked_sources,
        checked_tables=checked_tables,
        stale_sources=tuple(stale_sources),
        stale_tables=tuple(stale_tables),
        missing_sources=tuple(missing_sources),
        missing_tables=tuple(missing_tables),
        newest_input_ns=max(all_inputs, default=None),
        newest_output_ns=max(all_outputs, default=None),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root or find_project_root(Path(__file__))
    report = inspect_archive(root)
    print(report.compact())
    if report.newest_input_ns is not None:
        at = datetime.fromtimestamp(report.newest_input_ns / 1e9, timezone.utc)
        print(f"Newest checked input mtime: {at.isoformat()}")
    return 0 if report.status == "current" else 1


if __name__ == "__main__":
    raise SystemExit(main())
