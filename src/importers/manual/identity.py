"""Deterministic identities for records reconstructed from manual saves."""

from __future__ import annotations

import hashlib
import unicodedata
import uuid


MANUAL_ID_NAMESPACE = uuid.UUID("7f738c4c-2065-5f1d-b8a3-cc8b1e17ed51")


def normalize_manual_text(value: str) -> str:
    """Normalize representation without changing semantic whitespace."""
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _fingerprint(value: str) -> str:
    return hashlib.sha256(normalize_manual_text(value).encode("utf-8")).hexdigest()


def _stable_uuid(kind: str, *parts: object) -> str:
    name = "\x1f".join([kind, *(normalize_manual_text(str(part)) for part in parts)])
    return str(uuid.uuid5(MANUAL_ID_NAMESPACE, name))


def manual_conversation_id(source: str, input_key: str) -> str:
    return _stable_uuid("conversation", source, input_key)


def manual_message_id(
    conversation_id: str,
    role: str,
    content: str,
    occurrence: int,
) -> str:
    return _stable_uuid("message", conversation_id, role, _fingerprint(content), occurrence)


def manual_event_id(
    message_id: str,
    event_type: str,
    tool_name: str | None,
    payload: str,
    occurrence: int,
) -> str:
    return _stable_uuid(
        "event", message_id, event_type, tool_name or "", _fingerprint(payload), occurrence
    )

