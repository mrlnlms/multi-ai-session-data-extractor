"""Deterministic replay of preserved ChatGPT Canvas operations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


_TEXTDOC_ID_RE = re.compile(r"textdoc_id\s*:?\s*['\"]?([^'\"\s]+)", re.IGNORECASE)


@dataclass(frozen=True)
class CanvasSnapshot:
    document_id: str
    version: int
    name: str
    textdoc_type: str
    content: str
    request_message_id: str
    response_message_id: str | None
    create_time: object
    native_textdoc_id: str | None
    evidence: str


@dataclass
class _DocumentState:
    fallback_id: str
    name: str
    textdoc_type: str
    content: str | None
    native_id: str | None = None
    next_version: int = 1


@dataclass
class _PendingSnapshot:
    document: _DocumentState
    version: int
    content: str
    request_message_id: str
    response_message_id: str | None
    create_time: object
    evidence: str


def _json_part(message: dict) -> dict[str, Any] | None:
    parts = ((message.get("content") or {}).get("parts") or [])
    if not parts or not isinstance(parts[0], str):
        return None
    try:
        value = json.loads(parts[0])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def parse_canvas_payload(text: object) -> dict[str, Any] | None:
    """Parse plain or fenced JSON preserved by legacy flattened exports."""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if candidate.startswith("```json") and candidate.endswith("```"):
        candidate = candidate[7:-3].strip()
    elif candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _response_details(message: dict) -> tuple[bool, str | None]:
    parts = ((message.get("content") or {}).get("parts") or [])
    text = parts[0] if parts and isinstance(parts[0], str) else ""
    payload = _json_part(message)
    result = str(payload.get("result") or "") if payload else text
    native_id = str(payload["textdoc_id"]) if payload and payload.get("textdoc_id") else None
    if not native_id:
        match = _TEXTDOC_ID_RE.search(result)
        native_id = match.group(1) if match else None
    return result.strip().lower().startswith("successfully"), native_id


def _matching_response(mapping: dict, node: dict, recipient: str) -> tuple[str, dict] | None:
    matches: list[tuple[str, dict]] = []
    for child_id in node.get("children") or []:
        child = mapping.get(child_id) or {}
        message = child.get("message") or {}
        author = message.get("author") or {}
        if author.get("name") == recipient:
            matches.append((str(child_id), message))
    return matches[0] if len(matches) == 1 else None


def _javascript_replacement(match: re.Match, replacement: str) -> str:
    """Expand the JavaScript replacement tokens used by canmore patches."""
    output: list[str] = []
    index = 0
    while index < len(replacement):
        if replacement[index] != "$" or index + 1 >= len(replacement):
            output.append(replacement[index])
            index += 1
            continue
        token = replacement[index + 1]
        if token == "$":
            output.append("$")
            index += 2
        elif token == "&":
            output.append(match.group(0))
            index += 2
        elif token == "`":
            output.append(match.string[:match.start()])
            index += 2
        elif token == "'":
            output.append(match.string[match.end():])
            index += 2
        elif token.isdigit() and token != "0":
            end = index + 2
            while end < len(replacement) and end < index + 3 and replacement[end].isdigit():
                end += 1
            group_number = int(replacement[index + 1:end])
            if group_number <= (match.re.groups or 0):
                output.append(match.group(group_number) or "")
                index = end
            else:
                output.append("$")
                index += 1
        else:
            output.append("$")
            index += 1
    return "".join(output)


def _apply_updates(content: str | None, updates: object) -> str | None:
    if not isinstance(updates, list) or not updates:
        return None
    current = content
    for update in updates:
        if not isinstance(update, dict):
            return None
        pattern = update.get("pattern")
        replacement = update.get("replacement")
        if not isinstance(pattern, str) or not isinstance(replacement, str):
            return None
        if current is None:
            if pattern != ".*":
                return None
            current = replacement
            continue
        try:
            regex = re.compile(pattern, re.DOTALL)
            current, substitutions = regex.subn(
                lambda match: _javascript_replacement(match, replacement),
                current,
                count=0 if update.get("multiple") else 1,
            )
        except re.error:
            return None
        if substitutions == 0:
            return None
    return current


def replay_canvas_snapshots(
    conversation: dict,
    payload_fallbacks: Mapping[str, dict[str, Any]] | None = None,
) -> tuple[list[CanvasSnapshot], dict[str, int]]:
    """Replay create/update requests along each preserved conversation branch."""
    mapping = conversation.get("mapping") or {}
    report = {
        "creates": 0, "updates": 0, "snapshots": 0, "failed_upstream": 0,
        "unreconstructable": 0, "ambiguous": 0,
    }
    pending: list[_PendingSnapshot] = []
    resolved_ids: dict[str, str] = {}

    roots = sorted(
        (str(node_id) for node_id, node in mapping.items() if not (node or {}).get("parent")),
        key=str,
    )
    visited: set[str] = set()

    def walk(node_id: str, documents: dict[str, _DocumentState], active_key: str | None) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        node = mapping.get(node_id) or {}
        message = node.get("message") or {}
        recipient = message.get("recipient") or ""
        role = (message.get("author") or {}).get("role")
        payload = _json_part(message) or (payload_fallbacks or {}).get(node_id)
        branch_documents = {
            key: _DocumentState(
                fallback_id=value.fallback_id,
                name=value.name,
                textdoc_type=value.textdoc_type,
                content=value.content,
                native_id=value.native_id,
                next_version=value.next_version,
            )
            for key, value in documents.items()
        }
        # Preserve shared identity for snapshots already emitted on ancestors.
        for key, clone in branch_documents.items():
            original = documents[key]
            if original.native_id and not clone.native_id:
                clone.native_id = original.native_id

        if role == "assistant" and recipient in {"canmore.create_textdoc", "canmore.update_textdoc"}:
            response = _matching_response(mapping, node, recipient)
            response_id = response[0] if response else None
            success, native_id = _response_details(response[1]) if response else (False, None)

            if recipient == "canmore.create_textdoc":
                report["creates"] += 1
                content = payload.get("content") if payload else None
                if response and not success:
                    report["failed_upstream"] += 1
                else:
                    document = _DocumentState(
                        fallback_id=f"request-{node_id}",
                        name=str((payload or {}).get("name") or "untitled"),
                        textdoc_type=str((payload or {}).get("type") or "document"),
                        content=content if isinstance(content, str) else None,
                        native_id=native_id,
                        next_version=2 if isinstance(content, str) else 1,
                    )
                    if native_id:
                        resolved_ids[document.fallback_id] = native_id
                    key = native_id or document.fallback_id
                    branch_documents[key] = document
                    active_key = key
                    if isinstance(content, str):
                        pending.append(_PendingSnapshot(
                            document, 1, content, node_id, response_id,
                            message.get("create_time"), "confirmed" if success else "complete_request",
                        ))
                        report["snapshots"] += 1
                    else:
                        report["unreconstructable"] += 1
            else:
                report["updates"] += 1
                if not response:
                    report["ambiguous"] += 1
                    if active_key and active_key in branch_documents:
                        branch_documents[active_key].content = None
                elif not success:
                    report["failed_upstream"] += 1
                elif not payload:
                    report["unreconstructable"] += 1
                    if active_key and active_key in branch_documents:
                        branch_documents[active_key].content = None
                else:
                    requested_id = payload.get("textdoc_id") or native_id
                    key = str(requested_id) if requested_id and str(requested_id) in branch_documents else active_key
                    document = branch_documents.get(key or "")
                    if document is None:
                        report["unreconstructable"] += 1
                    elif document.native_id and native_id and document.native_id != native_id:
                        report["ambiguous"] += 1
                        document.content = None
                    else:
                        if native_id and not document.native_id:
                            document.native_id = native_id
                            resolved_ids[document.fallback_id] = native_id
                        updated = _apply_updates(document.content, payload.get("updates"))
                        if updated is None:
                            report["unreconstructable"] += 1
                            document.content = None
                        else:
                            document.content = updated
                            version = document.next_version
                            document.next_version += 1
                            if native_id and key != native_id:
                                branch_documents[native_id] = document
                                if key:
                                    branch_documents.pop(key, None)
                                active_key = native_id
                            pending.append(_PendingSnapshot(
                                document, version, updated, node_id, response_id,
                                message.get("create_time"), "confirmed",
                            ))
                            report["snapshots"] += 1

        children = sorted(
            (str(child_id) for child_id in node.get("children") or []),
            key=lambda child_id: (
                ((mapping.get(child_id) or {}).get("message") or {}).get("create_time") or 0,
                child_id,
            ),
        )
        for child_id in children:
            walk(child_id, branch_documents, active_key)

    for root in roots:
        walk(root, {}, None)
    for orphan in sorted(set(map(str, mapping)) - visited):
        walk(orphan, {}, None)

    snapshots = [
        CanvasSnapshot(
            document_id=(resolved_ids.get(item.document.fallback_id)
                         or item.document.native_id or item.document.fallback_id),
            version=item.version,
            name=item.document.name,
            textdoc_type=item.document.textdoc_type,
            content=item.content,
            request_message_id=item.request_message_id,
            response_message_id=item.response_message_id,
            create_time=item.create_time,
            native_textdoc_id=(resolved_ids.get(item.document.fallback_id)
                               or item.document.native_id),
            evidence=item.evidence,
        )
        for item in pending
    ]
    return snapshots, report
