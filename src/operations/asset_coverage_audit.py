"""Read-only census of preserved file representations across all sources.

The audit is deliberately conservative: it inventories preservation evidence
without mutating the archive and leaves semantic exclusions unresolved until a
versioned owner-approved policy exists.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Mapping, Sequence

import pandas as pd

from src.platforms.registry import KNOWN_PLATFORMS, WEB_PLATFORMS


CLI_PLATFORMS = frozenset(set(KNOWN_PLATFORMS) - set(WEB_PLATFORMS))
POLICY_PATH = Path(__file__).with_name("asset_coverage_policy.json")
ALLOWED_DISPOSITIONS = frozenset({
    "eligible", "domain_only", "external_reference", "operational",
    "derived_report", "duplicate_representation", "cache",
})
FINDING_STATUSES = frozenset({
    "covered", "eligible_uncovered", "excluded", "unresolved",
    "infrastructure", "duplicate_representation",
})
OPERATIONAL_NAMES = frozenset({
    "capture_log.json", "capture_log.jsonl", "discovery_ids.json",
    "reconcile_report.json", "last_capture.md", "last_reconcile.md",
})
CONTAINER_SUFFIXES = (".db", ".db-wal", ".db-shm", ".pb")


@dataclass(frozen=True)
class RepresentationEvidence:
    source: str
    account_scope: str
    representation_kind: str
    evidence_path: str
    native_id: str | None
    binary_path: str | None
    conversation_id: str | None
    message_id: str | None
    project_id: str | None
    observed_role: str | None


@dataclass(frozen=True)
class CoverageFinding:
    evidence: RepresentationEvidence
    status: str
    policy_disposition: str | None = None

    def __post_init__(self) -> None:
        if self.status not in FINDING_STATUSES:
            raise ValueError(f"unsupported coverage status: {self.status}")


def _relative_to_data(path: Path, data_root: Path) -> str:
    return path.relative_to(data_root).as_posix()


def _safe_regular_files(root: Path, data_root: Path) -> Iterator[Path]:
    """Yield files without following symlinks outside the archive root."""
    if not root.exists():
        return
    data_real = data_root.resolve()
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [d for d in dirs if not (current_path / d).is_symlink()]
        for name in sorted(files):
            path = current_path / name
            if path.is_symlink():
                try:
                    path.resolve().relative_to(data_real)
                except (OSError, ValueError):
                    continue
            if path.is_file():
                yield path


def iter_account_roots(source_root: Path) -> Iterator[tuple[str, Path]]:
    """Return the compatibility-default root and isolated account roots."""
    if not source_root.is_dir():
        return
    yield "default", source_root
    for child in sorted(source_root.iterdir()):
        if child.is_dir() and child.name.startswith("account-"):
            yield child.name, child


def _account_for(path: Path, source_root: Path) -> str:
    rel = path.relative_to(source_root)
    first = rel.parts[0] if rel.parts else ""
    return first if first.startswith("account-") else "default"


def _logical_rel(path: Path, source_root: Path) -> str:
    rel = path.relative_to(source_root)
    if rel.parts and rel.parts[0].startswith("account-"):
        rel = Path(*rel.parts[1:])
    return rel.as_posix()


def _kind_for_file(path: Path, source_root: Path, source: str) -> str:
    logical = PurePosixPath(_logical_rel(path, source_root))
    lower_name = logical.name.lower()
    parts = {part.lower() for part in logical.parts}
    if lower_name in OPERATIONAL_NAMES:
        return "capture_log" if "capture" in lower_name else "operational_record"
    if lower_name.endswith("manifest.json") or lower_name in {"assets_manifest.json", "assets_log.json"}:
        return "asset_manifest"
    if lower_name.endswith(CONTAINER_SUFFIXES):
        return "storage_container"
    if "assets" in parts and (
        lower_name.endswith(".meta.json")
        or lower_name.endswith("_meta.json")
        or "download_report" in lower_name
    ):
        return "asset_metadata_sidecar"
    if "assets" in parts or "_images" in parts or "project_sources" in parts:
        return "preserved_binary"
    if source == "Gemini CLI" and ("tool-outputs" in parts or "tool_output" in parts):
        return "tool_output_record"
    if lower_name == ".project_root" or lower_name == "logs.json":
        return "cli_operational_state"
    if "memory" in parts:
        return "agent_memory"
    if source in CLI_PLATFORMS and path.suffix.lower() in {".json", ".jsonl"}:
        return "cli_session_record"
    if "conversations" in parts or "sessions" in parts or path.suffix.lower() in {".json", ".jsonl"}:
        return "domain_record"
    return "unclassified_file"


def _filesystem_evidence(data_root: Path) -> list[RepresentationEvidence]:
    evidence: list[RepresentationEvidence] = []
    for layer in ("raw", "merged"):
        for source in KNOWN_PLATFORMS:
            source_root = data_root / layer / source
            for path in _safe_regular_files(source_root, data_root):
                account = _account_for(path, source_root)
                logical = _logical_rel(path, source_root)
                # Default-root traversal also sees account-* children. Assigning
                # from the path keeps each physical file in exactly one scope.
                binary = _relative_to_data(path, data_root) if _kind_for_file(path, source_root, source) == "preserved_binary" else None
                evidence.append(RepresentationEvidence(
                    source=source,
                    account_scope=account,
                    representation_kind=_kind_for_file(path, source_root, source),
                    evidence_path=_relative_to_data(path, data_root),
                    native_id=None,
                    binary_path=binary,
                    conversation_id=None,
                    message_id=None,
                    project_id=None,
                    observed_role=None,
                ))
    return evidence


def _walk(value: object) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _decoded_digest(data: str) -> str | None:
    try:
        payload = data.split(",", 1)[-1]
        return hashlib.sha256(base64.b64decode(payload, validate=True)).hexdigest()
    except (ValueError, TypeError):
        return None


def _record_evidence(data_root: Path) -> list[RepresentationEvidence]:
    """Read authoritative attachment shapes that are not physical files."""
    found: list[RepresentationEvidence] = []
    for source in ("Claude Code", "Codex", "Gemini CLI", "Antigravity CLI", "DeepSeek"):
        root = data_root / ("raw" if source in CLI_PLATFORMS else "merged") / source
        for path in _safe_regular_files(root, data_root):
            if path.suffix.lower() not in {".json", ".jsonl"}:
                continue
            try:
                records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.suffix.lower() == ".jsonl" else [json.loads(path.read_text(encoding="utf-8"))]
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                found.append(RepresentationEvidence(
                    source, _account_for(path, root), "malformed_evidence",
                    _relative_to_data(path, data_root), None, None,
                    None, None, None, None,
                ))
                continue
            account = _account_for(path, root)
            for record in records:
                for node in _walk(record):
                    node_type = str(node.get("type") or "").lower()
                    source_obj = node.get("source") if isinstance(node.get("source"), dict) else {}
                    payload = source_obj.get("data") if node_type == "image" else node.get("image_url")
                    if node_type in {"image", "input_image"} and isinstance(payload, str) and (source_obj.get("type") == "base64" or payload.startswith("data:")):
                        digest = _decoded_digest(payload)
                        if digest:
                            found.append(RepresentationEvidence(
                                source, account, "embedded_attachment",
                                _relative_to_data(path, data_root), digest, None,
                                str(record.get("sessionId") or record.get("conversation_id") or "") or None,
                                str(record.get("uuid") or record.get("message_id") or "") or None,
                                None, "input",
                            ))
                    if source in CLI_PLATFORMS:
                        for key in ("file_path", "path"):
                            if isinstance(node.get(key), str):
                                found.append(RepresentationEvidence(
                                    source, account, "tool_file_reference",
                                    _relative_to_data(path, data_root), None, None,
                                    None, None, None, None,
                                ))
                    files = node.get("files")
                    if source == "DeepSeek" and isinstance(files, list):
                        for ordinal, item in enumerate(files):
                            if not isinstance(item, dict):
                                continue
                            native = item.get("file_id") or item.get("id")
                            if native:
                                found.append(RepresentationEvidence(
                                    source, account, "native_file_record",
                                    _relative_to_data(path, data_root), str(native), None,
                                    str(record.get("chat_session", {}).get("id") or "") or None,
                                    str(node.get("message_id") or "") or None,
                                    None, "input",
                                ))
    return found


def _deduplicate(evidence: Iterable[RepresentationEvidence]) -> list[RepresentationEvidence]:
    """Collapse raw/merged copies while preferring merged paths."""
    chosen: dict[tuple, RepresentationEvidence] = {}
    for item in evidence:
        path = PurePosixPath(item.evidence_path)
        layerless = PurePosixPath(*path.parts[1:]).as_posix() if path.parts and path.parts[0] in {"raw", "merged"} else path.as_posix()
        binary = item.binary_path
        if binary:
            bp = PurePosixPath(binary)
            binary = PurePosixPath(*bp.parts[1:]).as_posix() if bp.parts and bp.parts[0] in {"raw", "merged"} else bp.as_posix()
        key = (item.source, item.account_scope, item.representation_kind, item.native_id, layerless, binary, item.message_id)
        old = chosen.get(key)
        if old is None or (item.evidence_path.startswith("merged/") and old.evidence_path.startswith("raw/")):
            chosen[key] = item
    return sorted(chosen.values(), key=lambda x: (x.source, x.account_scope, x.representation_kind, x.evidence_path, x.native_id or ""))


def inventory_preserved_session_assets(data_root: Path) -> list[RepresentationEvidence]:
    data_root = Path(data_root)
    return _deduplicate([*_filesystem_evidence(data_root), *_record_evidence(data_root)])


def _policy_matches(item: RepresentationEvidence, policy: Sequence[Mapping[str, str]]) -> list[Mapping[str, str]]:
    return [rule for rule in policy if rule.get("source") == item.source and rule.get("representation_kind") == item.representation_kind]


def load_policy(path: Path = POLICY_PATH) -> list[dict[str, str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("policy_version") != 1 or not isinstance(payload.get("rules"), list):
        raise ValueError("asset coverage policy must use policy_version=1 and a rules list")
    seen: set[tuple[str, str]] = set()
    rules: list[dict[str, str]] = []
    for rule in payload["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("asset coverage policy rule must be an object")
        source = rule.get("source")
        kind = rule.get("representation_kind")
        disposition = rule.get("disposition")
        if source not in KNOWN_PLATFORMS or "*" in str(source):
            raise ValueError(f"invalid policy source: {source}")
        if not kind or "*" in str(kind) or kind in {"all", "other", "unclassified_file"}:
            raise ValueError(f"invalid policy representation kind: {kind}")
        if disposition not in ALLOWED_DISPOSITIONS:
            raise ValueError(f"invalid policy disposition: {disposition}")
        if not isinstance(rule.get("reason"), str) or not rule["reason"].strip():
            raise ValueError("policy rule requires a public reason")
        key = (source, kind)
        if key in seen:
            raise ValueError(f"duplicate policy rule: {source}/{kind}")
        seen.add(key)
        rules.append(rule)
    return rules


def reconcile_asset_coverage(
    evidence: Iterable[RepresentationEvidence],
    assets: pd.DataFrame,
    links: pd.DataFrame,
    policy: Sequence[Mapping[str, str]] = (),
) -> list[CoverageFinding]:
    del links  # Relationship reconciliation is added once evidence identities are source-complete.
    asset_paths = set(assets.get("asset_path", pd.Series(dtype="string")).dropna().astype(str))
    asset_identity_counts: dict[tuple[str, str], int] = {}
    if not assets.empty and {"source", "asset_id"}.issubset(assets.columns):
        for source, asset_id in assets[["source", "asset_id"]].dropna().astype(str).itertuples(index=False, name=None):
            key = ("".join(ch for ch in source.lower() if ch.isalnum()), asset_id)
            asset_identity_counts[key] = asset_identity_counts.get(key, 0) + 1
    findings: list[CoverageFinding] = []
    for item in evidence:
        matches = _policy_matches(item, policy)
        if len(matches) > 1:
            findings.append(CoverageFinding(item, "unresolved"))
        elif item.representation_kind == "preserved_binary":
            status = "covered" if item.binary_path in asset_paths else "eligible_uncovered"
            findings.append(CoverageFinding(item, status))
        elif item.representation_kind == "embedded_attachment":
            findings.append(CoverageFinding(item, "eligible_uncovered"))
        elif item.representation_kind == "native_file_record" and item.native_id:
            source_key = "".join(ch for ch in item.source.lower() if ch.isalnum())
            count = asset_identity_counts.get((source_key, item.native_id), 0)
            findings.append(CoverageFinding(
                item, "covered" if count == 1 else "eligible_uncovered" if count == 0 else "unresolved"
            ))
        elif matches:
            findings.append(CoverageFinding(item, "excluded", matches[0].get("disposition")))
        elif item.representation_kind in {"capture_log", "operational_record"}:
            findings.append(CoverageFinding(item, "infrastructure"))
        else:
            findings.append(CoverageFinding(item, "unresolved"))
    return findings


def _secret_hash(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else None


def redacted_finding(finding: CoverageFinding) -> dict[str, object]:
    item = finding.evidence
    return {
        "source": item.source,
        "scope": "web" if item.source in WEB_PLATFORMS else "cli",
        "account_scope_hash": _secret_hash(item.account_scope),
        "representation_kind": item.representation_kind,
        "evidence_path_hash": _secret_hash(item.evidence_path),
        "native_id_hash": _secret_hash(item.native_id),
        "binary_path_hash": _secret_hash(item.binary_path),
        "has_conversation_relationship": item.conversation_id is not None,
        "has_message_relationship": item.message_id is not None,
        "has_project_relationship": item.project_id is not None,
        "observed_role": item.observed_role,
        "status": finding.status,
        "policy_disposition": finding.policy_disposition,
    }


def summarize_findings(findings: Iterable[CoverageFinding]) -> dict[str, object]:
    rows = list(findings)
    groups: dict[tuple[str, str, str], int] = {}
    for finding in rows:
        key = (finding.evidence.source, finding.evidence.representation_kind, finding.status)
        groups[key] = groups.get(key, 0) + 1
    return {
        "sources": list(KNOWN_PLATFORMS),
        "groups": [
            {"source": source, "representation_kind": kind, "status": status, "count": count}
            for (source, kind, status), count in sorted(groups.items())
        ],
        "totals": {status: sum(1 for row in rows if row.status == status) for status in sorted(FINDING_STATUSES)},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    assets = pd.read_parquet(args.data_root / "unified/assets.parquet")
    links = pd.read_parquet(args.data_root / "unified/asset_links.parquet")
    findings = reconcile_asset_coverage(
        inventory_preserved_session_assets(args.data_root), assets, links, load_policy()
    )
    summary = summarize_findings(findings)
    print(json.dumps(summary, indent=2, sort_keys=True) if args.json else summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
