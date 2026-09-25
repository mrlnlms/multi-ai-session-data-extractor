"""Preserve account memory responses before refreshing compatibility exports."""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from uuid import uuid4

from src.platforms.chatgpt.extractor.api_client import ChatGPTAPIClient
from src.platforms.chatgpt.extractor.models import CaptureReport

logger = logging.getLogger(__name__)
HISTORY_DIR = "_account_memory"


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".memory-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _memory_markdown(payload: dict) -> bytes:
    # Do not turn an unexpected/error response into an apparently empty export.
    entries = payload.get("memories")
    if entries is None:
        entries = payload.get("memory_entries")
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("content"), str)
        for entry in entries
    ):
        raise ValueError("Unexpected saved-memory response shape")
    return ("# ChatGPT Memories\n\n" + "\n".join(
        f"- {entry['content']}" for entry in entries
    )).encode("utf-8")


def _summary_payload(stream: str) -> dict:
    """Extract the complete native done event; retain other events in the raw SSE."""
    result = None
    # Only dispatch delimited events: an EOF during a data frame is incomplete.
    for frame in stream.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")[:-1]:
        event = "message"
        data = []
        for line in frame.split("\n"):
            field, separator, value = line.partition(":")
            if not separator:
                continue
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
        if event == "error":
            raise ValueError("Summary stream reported an error")
        if event == "done":
            if result is not None:
                raise ValueError("Duplicate summary completion event")
            result = json.loads("\n".join(data))
            if not isinstance(result, dict) or not isinstance(result.get("sections"), list):
                raise ValueError("Unexpected summary completion shape")
            if any(not isinstance(section, dict) for section in result["sections"]):
                raise ValueError("Unexpected summary section shape")
    if result is None:
        raise ValueError("Summary stream has no complete done event")
    return result


def _save_snapshot(
    output_dir: Path,
    surface: str,
    files: dict[str, bytes],
    request: dict,
    captured_at: datetime,
    *,
    complete: bool = True,
) -> None:
    """Publish an immutable capture, then atomically replace each current export.

    Previous exports are also retained byte-for-byte by hash. Their original
    capture date is unknown; filesystem mtimes are not treated as source dates.
    """
    history = output_dir / HISTORY_DIR
    parent = history / surface
    parent.mkdir(parents=True, exist_ok=True)
    capture_id = f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}"
    metadata = {
        "version": 1,
        "source": "chatgpt",
        "surface": surface,
        "complete": complete,
        "captured_at": captured_at.isoformat(),
        "request": request,
        "files": {
            name: {"sha256": hashlib.sha256(content).hexdigest()}
            for name, content in files.items()
        },
    }
    # Publish the entire snapshot together. An interrupted stage is never a
    # valid capture; an interrupted latest-export update still has its snapshot.
    with TemporaryDirectory(dir=parent, prefix=".capture-") as staging:
        stage = Path(staging)
        for name, content in files.items():
            _atomic_write(stage / name, content)
        _atomic_write(stage / "capture.json", _json_bytes(metadata))
        stage.rename(parent / capture_id)

    if not complete:
        return

    # Protect all existing files before replacing any compatibility export.
    for name in files:
        current = output_dir / name
        if current.is_file():
            previous = current.read_bytes()
            digest = hashlib.sha256(previous).hexdigest()
            preserved = history / "prior_exports" / name / digest
            if preserved.exists():
                if preserved.read_bytes() != previous:
                    raise ValueError("Prior account export hash mismatch")
            else:
                _atomic_write(preserved, previous)
    for name, content in files.items():
        _atomic_write(output_dir / name, content)


async def capture_account_memory(
    client: ChatGPTAPIClient, output_dir: Path, report: CaptureReport
) -> None:
    """Capture independent surfaces and report failures without deleting history."""
    for surface, fetch, endpoint, filename, params in (
        ("saved_memories", client.fetch_memories, "/backend-api/memories",
         "chatgpt_memories.json", {"include_memory_entries": "true"}),
        ("instructions", client.fetch_instructions, "/backend-api/user_system_messages",
         "chatgpt_instructions.json", {}),
        ("summary_checksum", client.fetch_memory_summary_checksum,
         "/backend-api/memories/about_you/summary/checksum",
         "chatgpt_memory_summary_checksum.json", {}),
    ):
        try:
            payload = await fetch()
            captured_at = datetime.now(timezone.utc)
            if not isinstance(payload, dict):
                raise ValueError("Expected an account response object")
            files = {filename: _json_bytes(payload)}
            if surface == "saved_memories":
                files["chatgpt_memories.md"] = _memory_markdown(payload)
            _save_snapshot(
                output_dir, surface, files,
                {"method": "GET", "path": endpoint, "params": params}, captured_at,
            )
        except Exception as exc:
            # Error bodies can contain personal text. Record only the stage/type.
            error_type = type(exc).__name__
            logger.warning("Account %s capture failed (%s)", surface, error_type)
            report.errors.append({"stage": f"account_{surface}", "error_type": error_type})

    try:
        stream = await client.fetch_memory_summary()
        captured_at = datetime.now(timezone.utc)
        request = {"method": "POST", "path": "/backend-api/memories/about_you/summary/stream", "json": {}}
        files = {"chatgpt_memory_summary.sse": stream.encode("utf-8")}
        try:
            summary = _summary_payload(stream)
        except (ValueError, TypeError):
            # Keep interrupted/native error streams as evidence, without
            # replacing the last complete summary or pretending it is empty.
            _save_snapshot(output_dir, "summary", files, request, captured_at, complete=False)
            raise
        files["chatgpt_memory_summary.json"] = _json_bytes(summary)
        _save_snapshot(output_dir, "summary", files, request, captured_at)
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning("Account summary capture failed (%s)", error_type)
        report.errors.append({"stage": "account_summary", "error_type": error_type})
