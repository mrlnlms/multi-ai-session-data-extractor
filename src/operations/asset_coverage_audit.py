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

from src.account_catalog import load_account_catalog
from src.platforms.registry import KNOWN_PLATFORMS, WEB_PLATFORMS
from src.platforms.claude_code.parser import make_embedded_image_asset_id
from src.platforms.codex.parser import make_input_image_asset_id
from src.platforms.antigravity_cli.parser import (
    AntigravityCLIParser,
    make_artifact_asset_id,
)


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
    "reconcile_report.json", "last_capture.md", "last_reconcile.md", ".ds_store",
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


@dataclass(frozen=True)
class CoverageReport:
    """Complete reconciliation result used by publication gates."""

    findings: tuple[CoverageFinding, ...]
    web_sources: tuple[str, ...]
    cli_sources: tuple[str, ...]
    ambiguous_policy_matches: int
    available_path_failures: int
    unresolved_asset_links: int
    eligible_identity_failures: int
    accounting_failures: int
    scope_integrity: Mapping[str, Mapping[str, int]]


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
    if source in {"ChatGPT", "Claude.ai"} and lower_name in {
        "chatgpt_memories.md", "claude_ai_memory.md",
    }:
        return "memory_export"
    if source == "ChatGPT" and "project_sources" in parts and lower_name == "_files.json":
        return "project_source_index"
    if source == "ChatGPT" and "canvases" in parts and "__patch_" in lower_name:
        return "canvas_patch_record"
    if source == "NotebookLM" and "assets" in parts:
        if "notes" in parts:
            return "notebooklm_note_materialization"
    if source == "Perplexity" and "assets" in parts and lower_name in {
        "_index.json", "_pinned_raw.json",
    }:
        return "domain_record"
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
    if "assets" in parts or "_images" in parts or "_artifacts" in parts or "project_sources" in parts:
        return "preserved_binary"
    if source == "Gemini CLI" and ("tool-outputs" in parts or "tool_output" in parts):
        return "tool_output_record"
    if source == "Gemini CLI" and "background-processes" in parts:
        return "cli_background_log"
    if source == "Gemini CLI" and "bin" in parts:
        return "cli_bundled_binary"
    if source == "Gemini CLI" and ".invalid_json." in lower_name:
        return "cli_recovery_backup"
    if lower_name == ".project_root" or lower_name == "logs.json":
        return "cli_operational_state"
    if "memory" in parts:
        return "agent_memory"
    if source in CLI_PLATFORMS and path.suffix.lower() in {".json", ".jsonl"}:
        return "cli_session_record"
    if "conversations" in parts or "sessions" in parts or path.suffix.lower() in {".json", ".jsonl"}:
        return "domain_record"
    return "unclassified_file"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _perplexity_verified_duplicate_ids(account_root: Path) -> dict[str, str]:
    """Map slugs only when native lineage and preserved bytes both agree."""
    index_path = account_root / "assets" / "_index.json"
    files_root = account_root / "assets" / "files"
    if not index_path.is_file() or not files_root.is_dir():
        return {}
    try:
        rows = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    by_native_id: dict[str, list[tuple[str, Path]]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("asset_id") or not row.get("asset_slug"):
            continue
        slug = str(row["asset_slug"])
        matches = [path for path in files_root.glob(f"{slug}.*") if path.is_file()]
        if len(matches) == 1:
            by_native_id.setdefault(str(row["asset_id"]), []).append((slug, matches[0]))
    verified: dict[str, str] = {}
    for native_id, representations in by_native_id.items():
        if len(representations) < 2:
            continue
        digests = {_sha256_file(path) for _, path in representations}
        if len(digests) == 1:
            verified.update({slug: native_id for slug, _ in representations})
    return verified


def _qwen_verified_manifest_lineage(
    account_root: Path,
) -> tuple[dict[str, str], set[str]]:
    """Resolve current/legacy paths only when preserved bytes prove lineage."""
    manifest_path = account_root / "assets_manifest.json"
    if not manifest_path.is_file():
        return {}, set()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, set()
    candidates: dict[str, set[str]] = {}
    listed: dict[str, set[str]] = {}
    for entry in payload.values() if isinstance(payload, dict) else []:
        if not isinstance(entry, dict) or not entry.get("file_id") or not entry.get("relpath"):
            continue
        current_rel = str(entry["relpath"])
        current = account_root / "assets" / current_rel
        if not current.is_file():
            continue
        native_id = str(entry["file_id"])
        candidates.setdefault(current_rel, set()).add(native_id)
        for previous_rel in entry.get("previous_relpaths") or []:
            listed.setdefault(str(previous_rel), set()).add(native_id)
            previous = account_root / "assets" / str(previous_rel)
            if previous.is_file() and _sha256_file(previous) == _sha256_file(current):
                candidates.setdefault(str(previous_rel), set()).add(native_id)
    unique = {
        f"assets/{relpath}": next(iter(native_ids))
        for relpath, native_ids in candidates.items()
        if len(native_ids) == 1
    }
    duplicates = {
        f"assets/{relpath}"
        for relpath, native_ids in candidates.items()
        if len(native_ids) > 1 and native_ids == listed.get(relpath)
    }
    return unique, duplicates


def _chatgpt_verified_canvas_duplicates(account_root: Path) -> set[str]:
    """Identify legacy Canvas files only when replay bytes and message lineage agree."""
    canvas_root = account_root / "assets" / "canvases"
    replay_by_message: dict[str, set[str]] = {}
    legacy: list[tuple[Path, str]] = []
    for meta_path in sorted(canvas_root.glob("*/*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        message_id = meta.get("message_id")
        content_path = Path(str(meta_path)[:-len(".meta.json")])
        if not message_id or not content_path.is_file():
            continue
        if meta.get("materialization") == "canvas_replay_v1":
            replay_by_message.setdefault(str(message_id), set()).add(_sha256_file(content_path))
        else:
            legacy.append((content_path, str(message_id)))
    return {
        _logical_rel(path, account_root)
        for path, message_id in legacy
        if _sha256_file(path) in replay_by_message.get(message_id, set())
    }


def _filesystem_evidence(data_root: Path) -> list[RepresentationEvidence]:
    evidence: list[RepresentationEvidence] = []
    perplexity_duplicate_ids: dict[tuple[str, str], str] = {}
    qwen_manifest_ids: dict[tuple[str, str], str] = {}
    qwen_verified_duplicates: set[tuple[str, str]] = set()
    chatgpt_canvas_duplicates: set[tuple[str, str]] = set()
    for account, account_root in iter_account_roots(data_root / "merged" / "Perplexity"):
        perplexity_duplicate_ids.update({
            (account, slug): native_id
            for slug, native_id in _perplexity_verified_duplicate_ids(account_root).items()
        })
    for account, account_root in iter_account_roots(data_root / "merged" / "Qwen"):
        manifest_ids, verified_duplicates = _qwen_verified_manifest_lineage(account_root)
        qwen_manifest_ids.update({
            (account, logical): native_id
            for logical, native_id in manifest_ids.items()
        })
        qwen_verified_duplicates.update(
            (account, logical) for logical in verified_duplicates
        )
    for layer in ("raw", "merged"):
        for account, account_root in iter_account_roots(data_root / layer / "ChatGPT"):
            chatgpt_canvas_duplicates.update(
                (account, logical)
                for logical in _chatgpt_verified_canvas_duplicates(account_root)
            )
    for layer in ("raw", "merged"):
        for source in KNOWN_PLATFORMS:
            source_root = data_root / layer / source
            for path in _safe_regular_files(source_root, data_root):
                account = _account_for(path, source_root)
                logical = _logical_rel(path, source_root)
                # Default-root traversal also sees account-* children. Assigning
                # from the path keeps each physical file in exactly one scope.
                kind = _kind_for_file(path, source_root, source)
                if source == "Qwen" and (account, logical) in qwen_verified_duplicates:
                    kind = "verified_duplicate_representation"
                if source == "ChatGPT" and (account, logical) in chatgpt_canvas_duplicates:
                    kind = "verified_duplicate_representation"
                if kind == "notebooklm_note_materialization":
                    try:
                        lines = path.read_text(encoding="utf-8").splitlines()
                        body = "\n".join(lines[2:] if len(lines) > 1 and not lines[1] else lines).strip()
                    except (OSError, UnicodeDecodeError):
                        body = ""
                    if not body or (len(body) == 36 and body.count("-") == 4):
                        kind = "notebooklm_note_reference_materialization"
                binary = (
                    _relative_to_data(path, data_root)
                    if kind in {"preserved_binary", "notebooklm_note_materialization"}
                    else None
                )
                # Gemini and Qwen generated files without an upstream file ID
                # use the preserved content digest as canonical identity.
                # Carry it in the census so a second physical copy can be
                # distinguished from genuinely uncovered content. Other
                # sources may use native IDs and are left unchanged here.
                native_id = None
                if source == "Qwen" and kind == "preserved_binary":
                    native_id = qwen_manifest_ids.get((account, logical))
                    if native_id is None:
                        native_id = f"sha256:{_sha256_file(path)}"
                elif source == "Gemini" and kind == "preserved_binary":
                    native_id = f"sha256:{_sha256_file(path)}"
                elif source == "Perplexity" and kind == "preserved_binary":
                    native_id = perplexity_duplicate_ids.get((account, path.stem))
                evidence.append(RepresentationEvidence(
                    source=source,
                    account_scope=account,
                    representation_kind=kind,
                    evidence_path=_relative_to_data(path, data_root),
                    native_id=native_id,
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
            if source == "Claude Code":
                continue
            try:
                records = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()] if path.suffix.lower() == ".jsonl" else [json.loads(path.read_text(encoding="utf-8"))]
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
                    if source != "Codex" and node_type in {"image", "input_image"} and isinstance(payload, str) and (source_obj.get("type") == "base64" or payload.startswith("data:")):
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


def _claude_code_embedded_evidence(data_root: Path) -> list[RepresentationEvidence]:
    """Inventory Claude Code images with the parser's exact locator semantics."""
    source = "Claude Code"
    root = data_root / "raw" / source
    found: list[RepresentationEvidence] = []
    for path in _safe_regular_files(root, data_root):
        if path.suffix.lower() != ".jsonl":
            continue
        events: list[dict] = []
        seen_uuids: set[str] = set()
        malformed = False
        try:
            # JSON strings may legally contain Unicode separators that
            # str.splitlines() treats as boundaries. JSONL is delimited only
            # by LF here, matching the source parser.
            lines = path.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            lines = []
            malformed = True
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed = True
                continue
            uuid = event.get("uuid")
            if uuid and uuid in seen_uuids:
                continue
            if uuid:
                seen_uuids.add(uuid)
            events.append(event)
        if malformed:
            found.append(RepresentationEvidence(
                source, "default", "malformed_evidence",
                _relative_to_data(path, data_root), None, None,
                None, None, None, None,
            ))

        is_subagent = "subagents" in path.parts
        if not is_subagent:
            events = [event for event in events if not event.get("isSidechain", False)]
        session_id = path.stem if is_subagent else None
        sequence = 0
        for event in events:
            if not session_id:
                session_id = event.get("sessionId")
            event_type = event.get("type")
            if event_type == "assistant":
                sequence += 1
                continue
            if event_type != "user":
                continue
            content = (event.get("message") or {}).get("content", [])
            if isinstance(content, str):
                if content.strip():
                    sequence += 1
                continue
            if not isinstance(content, list):
                continue
            images = [
                (index, item) for index, item in enumerate(content)
                if isinstance(item, dict) and item.get("type") == "image"
            ]
            has_text = any(
                isinstance(item, dict) and item.get("type") == "text"
                for item in content
            )
            if not has_text and not images:
                continue
            sequence += 1
            message_id = str(event.get("uuid") or f"{session_id}_{sequence}")
            for image_ordinal, (content_index, block) in enumerate(images):
                source_obj = block.get("source") or {}
                data = source_obj.get("data")
                if source_obj.get("type") != "base64" or not isinstance(data, str):
                    continue
                digest = _decoded_digest(data)
                if not digest or not session_id:
                    continue
                extension = {
                    "image/jpeg": ".jpg", "image/jpg": ".jpg",
                    "image/png": ".png", "image/gif": ".gif",
                    "image/webp": ".webp",
                }.get(source_obj.get("media_type") or "", ".bin")
                binary_path = (
                    f"raw/Claude Code/_images/{session_id}/"
                    f"{sequence}_{image_ordinal}{extension}"
                )
                found.append(RepresentationEvidence(
                    source=source,
                    account_scope="default",
                    representation_kind="embedded_attachment",
                    evidence_path=_relative_to_data(path, data_root),
                    native_id=make_embedded_image_asset_id(
                        str(session_id), message_id, content_index, digest
                    ),
                    binary_path=binary_path,
                    conversation_id=str(session_id),
                    message_id=message_id,
                    project_id=None,
                    observed_role="input",
                ))
    return found


def _codex_embedded_evidence(data_root: Path) -> list[RepresentationEvidence]:
    """Inventory only user-message input images, excluding tool envelopes."""
    source = "Codex"
    root = data_root / "raw" / source
    found: list[RepresentationEvidence] = []
    for path in _safe_regular_files(root, data_root):
        if not path.name.startswith("rollout-") or path.suffix != ".jsonl":
            continue
        events: list[dict] = []
        malformed = False
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            lines = []
            malformed = True
        for line in lines:
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                malformed = True
        if malformed:
            found.append(RepresentationEvidence(
                source, "default", "malformed_evidence",
                _relative_to_data(path, data_root), None, None,
                None, None, None, None,
            ))
        meta = next(
            ((event.get("payload") or {}) for event in events
             if event.get("type") == "session_meta"),
            None,
        )
        if not meta or not meta.get("id"):
            continue
        session_id = str(meta["id"])
        legacy: list[dict] = []
        response: list[dict] = []
        for index, event in enumerate(events):
            payload = event.get("payload") or {}
            if event.get("type") == "event_msg" and payload.get("type") in {
                "user_message", "agent_message",
            }:
                images: list[tuple[int, str]] = []
                if payload.get("type") == "user_message" and index > 0:
                    previous = events[index - 1]
                    previous_payload = previous.get("payload") or {}
                    if (
                        previous.get("type") == "response_item"
                        and previous_payload.get("type") == "message"
                        and previous_payload.get("role") == "user"
                    ):
                        images = [
                            (block_index, item["image_url"])
                            for block_index, item in enumerate(previous_payload.get("content") or [])
                            if isinstance(item, dict)
                            and item.get("type") == "input_image"
                            and isinstance(item.get("image_url"), str)
                            and item["image_url"].startswith("data:")
                        ]
                legacy.append({
                    "role": "user" if payload.get("type") == "user_message" else "assistant",
                    "timestamp": event.get("timestamp"), "images": images,
                })
            elif (
                event.get("type") == "response_item"
                and payload.get("type") == "message"
                and payload.get("role") in {"user", "assistant"}
            ):
                response.append({
                    "role": payload["role"], "timestamp": event.get("timestamp"),
                    "images": [
                        (block_index, item["image_url"])
                        for block_index, item in enumerate(payload.get("content") or [])
                        if isinstance(item, dict)
                        and item.get("type") == "input_image"
                        and isinstance(item.get("image_url"), str)
                        and item["image_url"].startswith("data:")
                    ],
                })
        selected = legacy if legacy else response
        for sequence, message in enumerate(
            sorted(selected, key=lambda item: item["timestamp"] or ""), 1
        ):
            message_id = f"{session_id}_{sequence}"
            for image_ordinal, (content_index, data_uri) in enumerate(message["images"]):
                digest = _decoded_digest(data_uri)
                if not digest:
                    continue
                header = data_uri.split(",", 1)[0]
                mime_type = header[5:].split(";", 1)[0]
                extension = {
                    "image/jpeg": ".jpg", "image/png": ".png",
                    "image/gif": ".gif", "image/webp": ".webp",
                }.get(mime_type, ".bin")
                found.append(RepresentationEvidence(
                    source=source, account_scope="default",
                    representation_kind="embedded_attachment",
                    evidence_path=_relative_to_data(path, data_root),
                    native_id=make_input_image_asset_id(
                        session_id, message_id, content_index, digest
                    ),
                    binary_path=(
                        f"raw/Codex/_images/{session_id}/"
                        f"{sequence}_{image_ordinal}{extension}"
                    ),
                    conversation_id=session_id, message_id=message_id,
                    project_id=None, observed_role="input",
                ))
    return found


def _antigravity_artifact_evidence(data_root: Path) -> list[RepresentationEvidence]:
    """Inventory explicit artifact payloads from decoded trajectories."""
    source = "Antigravity CLI"
    root = data_root / "raw" / source
    found: list[RepresentationEvidence] = []

    def add_tool_calls(
        evidence_path: Path,
        conversation_id: str,
        message_id: str,
        tool_calls: object,
    ) -> None:
        if not isinstance(tool_calls, list):
            return
        for tool_index, tool_call in enumerate(tool_calls):
            payload = AntigravityCLIParser._artifact_payload(tool_call)
            if payload is None:
                continue
            target, content, _metadata = payload
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            suffix = Path(target).suffix or ".txt"
            found.append(RepresentationEvidence(
                source=source, account_scope="default",
                representation_kind="generated_artifact_record",
                evidence_path=_relative_to_data(evidence_path, data_root),
                native_id=make_artifact_asset_id(
                    conversation_id, message_id, tool_index, digest
                ),
                binary_path=(
                    f"raw/Antigravity CLI/_artifacts/{conversation_id}/"
                    f"{message_id.rsplit('_', 1)[-1]}_{tool_index}{suffix}"
                ),
                conversation_id=conversation_id, message_id=message_id,
                project_id=None, observed_role="output",
            ))

    current_ids: set[str] = set()
    brain = root / "brain"
    for path in sorted(brain.glob("*/.system_generated/logs/transcript.jsonl")):
        conversation_id = path.parent.parent.parent.name
        current_ids.add(conversation_id)
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        for record_index, line in enumerate(line for line in lines if line.strip()):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "PLANNER_RESPONSE" or record.get("source") != "MODEL":
                continue
            step_index = record.get("step_index", record_index)
            if not isinstance(step_index, int):
                step_index = record_index
            add_tool_calls(
                path, conversation_id, f"{conversation_id}_step_{step_index}",
                record.get("tool_calls"),
            )

    for path in sorted((root / "recovered").glob("*.trajectory.json")):
        fallback_id = path.name.removesuffix(".trajectory.json")
        if fallback_id in current_ids:
            continue
        try:
            trajectory = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        conversation_id = str(trajectory.get("cascadeId") or fallback_id)
        for step_index, step in enumerate(trajectory.get("steps") or []):
            if not isinstance(step, dict):
                continue
            kind = str(step.get("type") or "").removeprefix("CORTEX_STEP_TYPE_")
            if kind != "PLANNER_RESPONSE":
                continue
            response = step.get("plannerResponse") or {}
            add_tool_calls(
                path, conversation_id,
                f"{conversation_id}_legacy_step_{step_index}",
                response.get("toolCalls", response.get("tool_calls"))
                if isinstance(response, dict) else None,
            )
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
    return _deduplicate([
        *_filesystem_evidence(data_root),
        *_record_evidence(data_root),
        *_claude_code_embedded_evidence(data_root),
        *_codex_embedded_evidence(data_root),
        *_antigravity_artifact_evidence(data_root),
    ])


def inventory_legacy_asset_files(data_root: Path) -> list[RepresentationEvidence]:
    """Return every physical raw/merged asset copy without layer deduplication."""
    return [
        item
        for item in _filesystem_evidence(Path(data_root))
        if item.representation_kind in {
            "preserved_binary",
            "notebooklm_note_materialization",
            "verified_duplicate_representation",
        }
    ]


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


def _asset_path_matches_account(path: str, source: str, account_scope: str) -> bool:
    """Match canonical paths to the census account tree without display labels."""
    parts = PurePosixPath(path).parts
    try:
        source_index = parts.index(source)
    except ValueError:
        return False
    child = parts[source_index + 1] if source_index + 1 < len(parts) else ""
    return child == account_scope if account_scope.startswith("account-") else not child.startswith("account-")


def _vault_blob_digest(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if len(parts) != 5 or parts[:3] != ("assets", "blobs", "sha256"):
        return None
    digest = parts[4]
    if parts[3] != digest[:2] or len(digest) != 64:
        return None
    try:
        int(digest, 16)
    except ValueError:
        return None
    return digest


def _evidence_digest(
    item: RepresentationEvidence,
    data_root: Path | None,
    cache: dict[str, str | None],
) -> str | None:
    if item.binary_path is None or data_root is None:
        return None
    if item.binary_path in cache:
        return cache[item.binary_path]
    path = Path(data_root) / item.binary_path
    if not path.is_file():
        cache[item.binary_path] = None
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cache[item.binary_path] = digest
    return digest


def reconcile_asset_coverage(
    evidence: Iterable[RepresentationEvidence],
    assets: pd.DataFrame,
    links: pd.DataFrame,
    policy: Sequence[Mapping[str, str]] = (),
    *,
    data_root: Path | None = None,
) -> list[CoverageFinding]:
    del links  # Relationship reconciliation is added once evidence identities are source-complete.
    asset_paths = set(assets.get("asset_path", pd.Series(dtype="string")).dropna().astype(str))
    asset_identity_paths: dict[tuple[str, str], set[str]] = {}
    asset_identity_counts: dict[tuple[str, str], int] = {}
    asset_digests: set[tuple[str, str]] = set()
    if not assets.empty and {"source", "asset_id"}.issubset(assets.columns):
        for source, asset_id in assets[["source", "asset_id"]].dropna().astype(str).itertuples(index=False, name=None):
            key = ("".join(ch for ch in source.lower() if ch.isalnum()), asset_id)
            asset_identity_counts[key] = asset_identity_counts.get(key, 0) + 1
        for source, asset_id, asset_path in assets[
            ["source", "asset_id", "asset_path"]
        ].dropna().astype(str).itertuples(index=False, name=None):
            key = ("".join(ch for ch in source.lower() if ch.isalnum()), asset_id)
            asset_identity_paths.setdefault(key, set()).add(asset_path)
            digest = _vault_blob_digest(asset_path)
            if digest is not None:
                asset_digests.add((key[0], digest))
    findings: list[CoverageFinding] = []
    digest_cache: dict[str, str | None] = {}
    for item in evidence:
        matches = _policy_matches(item, policy)
        source_key = "".join(ch for ch in item.source.lower() if ch.isalnum())
        digest = _evidence_digest(item, data_root, digest_cache)
        binary_is_covered = (
            item.binary_path is None
            or item.binary_path in asset_paths
            or (digest is not None and (source_key, digest) in asset_digests)
        )
        if len(matches) > 1:
            findings.append(CoverageFinding(item, "unresolved"))
        elif item.representation_kind in {
            "preserved_binary", "notebooklm_note_materialization",
        }:
            status = "covered" if binary_is_covered else "eligible_uncovered"
            if status == "eligible_uncovered" and item.native_id:
                identity_paths = asset_identity_paths.get((source_key, item.native_id), set())
                if any(
                    _asset_path_matches_account(path, item.source, item.account_scope)
                    for path in identity_paths
                ):
                    status = "duplicate_representation"
            findings.append(CoverageFinding(item, status))
        elif item.representation_kind == "embedded_attachment":
            identity_count = asset_identity_counts.get((source_key, item.native_id or ""), 0)
            findings.append(CoverageFinding(
                item,
                "covered" if identity_count == 1 and binary_is_covered else
                "eligible_uncovered" if identity_count == 0 or not binary_is_covered else
                "unresolved",
            ))
        elif item.representation_kind in {"native_file_record", "generated_artifact_record"} and item.native_id:
            count = asset_identity_counts.get((source_key, item.native_id), 0)
            findings.append(CoverageFinding(
                item,
                "covered" if count == 1 and binary_is_covered else
                "eligible_uncovered" if count == 0 or not binary_is_covered else
                "unresolved",
            ))
        elif item.representation_kind == "verified_duplicate_representation":
            findings.append(CoverageFinding(item, "duplicate_representation"))
        elif matches:
            findings.append(CoverageFinding(item, "excluded", matches[0].get("disposition")))
        elif item.representation_kind in {"capture_log", "operational_record"}:
            findings.append(CoverageFinding(item, "infrastructure"))
        else:
            findings.append(CoverageFinding(item, "unresolved"))
    return findings


def _source_key(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _account_key(value: object) -> str | None:
    return None if pd.isna(value) else str(value)


def build_coverage_report(
    evidence: Iterable[RepresentationEvidence],
    assets: pd.DataFrame,
    links: pd.DataFrame,
    policy: Sequence[Mapping[str, str]] = (),
    *,
    data_root: Path | None = None,
) -> CoverageReport:
    """Build the invariant report without weakening source-specific policy."""
    evidence_rows = list(evidence)
    account_ids: dict[tuple[str, str], str] = {}
    if data_root is not None:
        catalog = load_account_catalog(Path(data_root) / "accounts" / "catalog.json")
        account_ids = {
            (record.platform, record.technical_key): record.account_id
            for record in catalog.records
        }
    findings = tuple(
        reconcile_asset_coverage(
            evidence_rows, assets, links, policy, data_root=data_root
        )
    )
    ambiguous = sum(len(_policy_matches(item, policy)) > 1 for item in evidence_rows)

    asset_rows_by_path: dict[str, set[tuple[str, str | None, str]]] = {}
    asset_keys: set[tuple[str, str | None, str]] = set()
    asset_keys_by_digest: dict[tuple[str, str], set[tuple[str, str | None, str]]] = {}
    integrity_by_scope = {
        "web": {"ambiguous_policy_matches": 0, "available_path_failures": 0,
                "unresolved_asset_links": 0, "eligible_identity_failures": 0},
        "cli": {"ambiguous_policy_matches": 0, "available_path_failures": 0,
                "unresolved_asset_links": 0, "eligible_identity_failures": 0},
    }
    for item in evidence_rows:
        if len(_policy_matches(item, policy)) > 1:
            scope = "web" if item.source in WEB_PLATFORMS else "cli"
            integrity_by_scope[scope]["ambiguous_policy_matches"] += 1

    available_path_failures = 0
    for row in assets.itertuples(index=False):
        key = (_source_key(row.source), _account_key(row.account_id), str(row.asset_id))
        asset_keys.add(key)
        path_value = None if pd.isna(row.asset_path) else str(row.asset_path)
        if path_value:
            asset_rows_by_path.setdefault(path_value, set()).add(key)
            digest = _vault_blob_digest(path_value)
            if digest is not None:
                asset_keys_by_digest.setdefault((key[0], digest), set()).add(key)
        if bool(row.is_binary_available):
            if not path_value or data_root is None or not (Path(data_root) / path_value).is_file():
                available_path_failures += 1
                scope = "web" if any(_source_key(row.source) == _source_key(source) for source in WEB_PLATFORMS) else "cli"
                integrity_by_scope[scope]["available_path_failures"] += 1

    eligible_identity_failures = 0
    ambiguous_evidence_ids: set[int] = set()
    digest_cache: dict[str, str | None] = {}
    eligible_kinds = {
        "preserved_binary", "notebooklm_note_materialization",
        "embedded_attachment", "native_file_record", "generated_artifact_record",
    }
    for item in evidence_rows:
        if item.representation_kind not in eligible_kinds:
            continue
        resolved_by_digest = False
        identities = set(asset_rows_by_path.get(item.binary_path or "", set()))
        if not identities and item.native_id:
            identities = {
                key for key in asset_keys
                if key[0] == _source_key(item.source) and key[2] == item.native_id
            }
        if not identities:
            digest = _evidence_digest(item, data_root, digest_cache)
            if digest is not None:
                identities = set(
                    asset_keys_by_digest.get((_source_key(item.source), digest), set())
                )
                resolved_by_digest = bool(identities)
        technical_key = item.account_scope.removeprefix("account-")
        expected_account_id = account_ids.get((item.source, technical_key))
        if expected_account_id is not None and len(identities) > 1:
            identities = {key for key in identities if key[1] == expected_account_id}
            resolved_by_digest = resolved_by_digest and bool(identities)
        if len(identities) != 1 and not resolved_by_digest:
            eligible_identity_failures += 1
            scope = "web" if item.source in WEB_PLATFORMS else "cli"
            integrity_by_scope[scope]["eligible_identity_failures"] += 1
            if len(identities) > 1:
                ambiguous_evidence_ids.add(id(item))

    if ambiguous_evidence_ids:
        findings = tuple(
            CoverageFinding(row.evidence, "unresolved")
            if id(row.evidence) in ambiguous_evidence_ids else row
            for row in findings
        )

    unresolved_links = 0
    for row in links.itertuples(index=False):
        key = (_source_key(row.source), _account_key(row.account_id), str(row.asset_id))
        if key not in asset_keys:
            unresolved_links += 1
            scope = "web" if any(_source_key(row.source) == _source_key(source) for source in WEB_PLATFORMS) else "cli"
            integrity_by_scope[scope]["unresolved_asset_links"] += 1

    return CoverageReport(
        findings=findings,
        web_sources=tuple(WEB_PLATFORMS),
        cli_sources=tuple(source for source in KNOWN_PLATFORMS if source in CLI_PLATFORMS),
        ambiguous_policy_matches=ambiguous,
        available_path_failures=available_path_failures,
        unresolved_asset_links=unresolved_links,
        eligible_identity_failures=eligible_identity_failures,
        accounting_failures=abs(len(evidence_rows) - len(findings)),
        scope_integrity=integrity_by_scope,
    )


def _assert_scope_coverage(report: CoverageReport, sources: set[str], label: str) -> None:
    scoped = [row for row in report.findings if row.evidence.source in sources]
    failures = {
        "eligible_uncovered": sum(row.status == "eligible_uncovered" for row in scoped),
        "unresolved": sum(row.status == "unresolved" for row in scoped),
        **report.scope_integrity[label.lower()],
        "accounting_failures": report.accounting_failures,
    }
    failed = {name: count for name, count in failures.items() if count}
    if failed:
        details = ", ".join(f"{name}={count}" for name, count in failed.items())
        raise AssertionError(f"{label} preserved-file coverage failed: {details}")


def assert_preserved_web_file_coverage(report: CoverageReport) -> None:
    if set(report.web_sources) != set(WEB_PLATFORMS):
        raise AssertionError(f"web source census is incomplete: {len(report.web_sources)}/9")
    _assert_scope_coverage(report, set(WEB_PLATFORMS), "web")


def assert_preserved_cli_session_asset_coverage(report: CoverageReport) -> None:
    if set(report.cli_sources) != set(CLI_PLATFORMS):
        raise AssertionError(f"CLI source census is incomplete: {len(report.cli_sources)}/4")
    _assert_scope_coverage(report, set(CLI_PLATFORMS), "CLI")


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


def _check_block(report: CoverageReport, scope: str) -> dict[str, int]:
    sources = set(WEB_PLATFORMS if scope == "web" else CLI_PLATFORMS)
    scoped = [row for row in report.findings if row.evidence.source in sources]
    return {
        f"{scope}_sources": len(report.web_sources if scope == "web" else report.cli_sources),
        "eligible_uncovered": sum(row.status == "eligible_uncovered" for row in scoped),
        "unresolved": sum(row.status == "unresolved" for row in scoped),
        "ambiguous_policy_matches": report.scope_integrity[scope]["ambiguous_policy_matches"],
        "available_path_failures": report.scope_integrity[scope]["available_path_failures"],
        "unresolved_asset_links": report.scope_integrity[scope]["unresolved_asset_links"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    assets = pd.read_parquet(args.data_root / "unified/assets.parquet")
    links = pd.read_parquet(args.data_root / "unified/asset_links.parquet")
    report = build_coverage_report(
        inventory_preserved_session_assets(args.data_root), assets, links,
        load_policy(), data_root=args.data_root,
    )
    summary = summarize_findings(report.findings)
    if args.check:
        blocks = {scope: _check_block(report, scope) for scope in ("web", "cli")}
        if args.json:
            print(json.dumps(blocks, indent=2, sort_keys=True))
        else:
            for scope, block in blocks.items():
                print(f"[{scope}]")
                for name, value in block.items():
                    print(f"{name}={value}")
        failures = []
        for assertion in (
            assert_preserved_web_file_coverage,
            assert_preserved_cli_session_asset_coverage,
        ):
            try:
                assertion(report)
            except AssertionError as exc:
                failures.append(str(exc))
        return 1 if failures else 0
    print(json.dumps(summary, indent=2, sort_keys=True) if args.json else summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
