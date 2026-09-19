"""Preview-first migration of legacy asset projections into an asset vault.

This exceptional operation never removes legacy evidence.  ``plan`` writes an
immutable description of the inputs; ``run`` verifies that description before
writing and requires an explicit flag for the canonical ``data/assets`` root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Sequence

import pandas as pd

from src.assets.state import canonical_json
from src.operations.verify_asset_vault import verify_vault
from src.workflows.asset_projection import project_source_assets, source_inputs_from_data


PLAN_VERSION = 1
SOURCE_ORDER = (
    "chatgpt",
    "claude_ai",
    "gemini",
    "notebooklm",
    "qwen",
    "deepseek",
    "perplexity",
    "grok",
    "kimi",
    "claude_code",
    "codex",
    "gemini_cli",
    "antigravity_cli",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _input_descriptor(path: Path, data_root: Path) -> dict[str, object]:
    relative = path.relative_to(data_root).as_posix()
    return {"path": relative, "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _source_plan(data_root: Path, source: str) -> dict[str, object]:
    inputs = source_inputs_from_data(data_root, source)
    paths = (inputs.assets_path, inputs.asset_links_path, inputs.messages_path)
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    assets = pd.read_parquet(inputs.assets_path, columns=["is_binary_available", "asset_path"])
    links = pd.read_parquet(inputs.asset_links_path, columns=["asset_link_id"])
    messages = pd.read_parquet(inputs.messages_path, columns=["asset_paths"])
    message_path_count = sum(len(value) for value in messages["asset_paths"] if value is not None)
    return {
        "source": source,
        "inputs": [_input_descriptor(path, data_root) for path in paths],
        "evidence_paths": [path.relative_to(data_root).as_posix() for path in inputs.evidence_paths],
        "expected": {
            "asset_count": len(assets),
            "link_count": len(links),
            "available_count": int(assets["is_binary_available"].sum()),
            "message_path_count": message_path_count,
        },
    }


def _plan_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def create_plan(data_root: Path, output: Path) -> dict[str, object]:
    """Create a deterministic plan without replacing an existing file."""
    data_root = Path(data_root).resolve()
    output = Path(output)
    payload: dict[str, object] = {
        "plan_version": PLAN_VERSION,
        "data_root": str(data_root),
        "canonical_vault_root": str((data_root / "assets").resolve()),
        "sources": [_source_plan(data_root, source) for source in SOURCE_ORDER],
    }
    plan = {**payload, "plan_sha256": _plan_digest(payload)}
    encoded = canonical_json(plan) + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                raise OSError("incomplete migration plan write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(output.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    output.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return plan


def load_plan(path: Path) -> dict[str, object]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict) or set(value) != {
        "plan_version", "data_root", "canonical_vault_root", "sources", "plan_sha256"
    }:
        raise ValueError("migration plan has unexpected fields")
    if value["plan_version"] != PLAN_VERSION:
        raise ValueError("unsupported migration plan version")
    supplied = value.pop("plan_sha256")
    expected = _plan_digest(value)
    value["plan_sha256"] = supplied
    if supplied != expected:
        raise ValueError("migration plan checksum mismatch")
    if not isinstance(value["sources"], list):
        raise ValueError("migration plan sources must be a list")
    return value


def _verify_inputs(plan: dict[str, object]) -> Path:
    data_root = Path(str(plan["data_root"]))
    for source in plan["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("inputs"), list):
            raise ValueError("migration plan source is malformed")
        for descriptor in source["inputs"]:
            if not isinstance(descriptor, dict):
                raise ValueError("migration plan input is malformed")
            path = data_root / str(descriptor["path"])
            if path.stat().st_size != descriptor["size_bytes"] or _sha256(path) != descriptor["sha256"]:
                raise ValueError(f"migration input changed after planning: {path}")
    return data_root


def _write_report(path: Path, report: dict[str, object]) -> None:
    encoded = canonical_json(report) + b"\n"
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"existing {path.name} differs from this migration")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def run_plan(
    plan_path: Path, vault_root: Path, *, apply_canonical: bool = False
) -> dict[str, object]:
    """Run a checked plan idempotently, preserving every legacy input."""
    plan = load_plan(plan_path)
    data_root = _verify_inputs(plan)
    vault_root = Path(vault_root).resolve()
    canonical_root = Path(str(plan["canonical_vault_root"])).resolve()
    if vault_root == canonical_root and not apply_canonical:
        raise PermissionError("refusing canonical asset vault root without --apply-canonical")
    if vault_root.name != "assets":
        raise ValueError("vault_root must be named 'assets' so projected paths remain data-relative")
    output_root = vault_root.parent
    source_reports: list[dict[str, object]] = []
    for entry in plan["sources"]:
        if not isinstance(entry, dict):
            raise ValueError("migration plan source is malformed")
        source = str(entry["source"])
        report = project_source_assets(
            source,
            source_inputs_from_data(data_root, source),
            vault_root,
            output_root,
        )
        observed = {
            "asset_count": report.asset_count,
            "link_count": report.link_count,
            "available_count": report.available_count,
            "message_path_count": report.message_path_count,
        }
        if observed != entry["expected"]:
            raise ValueError(f"migration totals differ from plan for {source}: {observed!r}")
        source_reports.append({"source": source, **observed})
    verification = verify_vault(vault_root, plan=plan)
    result = {
        "plan_sha256": plan["plan_sha256"],
        "vault_root": str(vault_root),
        "sources": source_reports,
        "verification": verification,
    }
    _write_report(output_root / "asset-vault-migration-report.json", result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="write an immutable migration preview")
    plan.add_argument("--data-root", type=Path, default=Path("data"))
    plan.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="execute an existing immutable plan")
    run.add_argument("plan", type=Path)
    run.add_argument("--vault-root", type=Path, required=True)
    run.add_argument("--apply-canonical", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "plan":
        result = create_plan(args.data_root, args.output)
    else:
        result = run_plan(args.plan, args.vault_root, apply_canonical=args.apply_canonical)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
