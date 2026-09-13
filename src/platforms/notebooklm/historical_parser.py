"""Adapter for immutable NotebookLM snapshots from inaccessible accounts.

Historical snapshots predate the current batchexecute capture format, but they
are still first-class NotebookLM data.  This module converts every snapshot
directory below a configured root to the same schema used by the live parser.
"""

from __future__ import annotations

import json
import re
import uuid as uuid_lib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.schema.models import (
    Branch,
    Conversation,
    Message,
    NotebookLMGuideQuestion,
    NotebookLMNote,
    NotebookLMOutput,
    ProjectDoc,
)


SOURCE = "notebooklm"
HISTORICAL_CAPTURE_METHOD = "historical_notebooklm_snapshot"
_ID_NAMESPACE = uuid_lib.UUID("bb0cb4fa-c112-4b65-b7db-0187dd9faef5")
_EXT_TO_OUTPUT = {
    ".m4a": (1, "audio_overview"),
    ".mp4": (3, "video_overview"),
    ".pdf": (8, "slide_deck"),
    ".png": (9, "infographic"),
}

@dataclass
class NotebookLMHistoricalResult:
    """Canonical rows decoded from one or more historical snapshots."""

    conversations: list[Conversation] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    tool_events: list = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    sources: list[ProjectDoc] = field(default_factory=list)
    notes: list[NotebookLMNote] = field(default_factory=list)
    outputs: list[NotebookLMOutput] = field(default_factory=list)
    guide_questions: list[NotebookLMGuideQuestion] = field(default_factory=list)

    def extend(self, other: "NotebookLMHistoricalResult") -> None:
        for name in (
            "conversations",
            "messages",
            "tool_events",
            "branches",
            "sources",
            "notes",
            "outputs",
            "guide_questions",
        ):
            getattr(self, name).extend(getattr(other, name))


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not key:
        raise ValueError("historical archive directory must have a usable name")
    return key


def _stable_id(*parts: object) -> str:
    return str(uuid_lib.uuid5(_ID_NAMESPACE, ":".join(map(str, parts))))


def _capture_timestamp(archive_key: str) -> pd.Timestamp:
    """Return a stable capture date encoded in the snapshot directory name."""

    match = re.search(r"(?:^|[^0-9])(20\d{2}-\d{2}-\d{2})(?:$|[^0-9])", archive_key)
    if match is None:
        raise ValueError(
            "historical archive directory must include its capture date as YYYY-MM-DD: "
            f"{archive_key}"
        )
    return pd.Timestamp(match.group(1), tz="UTC")


class NotebookLMHistoricalParser:
    """Convert one old-format snapshot directory to canonical model rows."""

    def __init__(self, archive_key: str):
        self.archive_key = _safe_key(archive_key)
        self.account = f"archive:{self.archive_key}"
        self.captured_at = _capture_timestamp(self.archive_key)

    def parse(self, input_path: Path) -> NotebookLMHistoricalResult:
        input_path = Path(input_path)
        result = NotebookLMHistoricalResult()
        for notebook_dir in sorted(input_path.iterdir()):
            notebook_json = notebook_dir / "notebook.json"
            if not notebook_dir.is_dir() or not notebook_json.is_file():
                continue
            notebook_result = NotebookLMHistoricalResult()
            self._parse_notebook(notebook_dir, notebook_json, notebook_result)
            result.extend(notebook_result)
        return result

    def _parse_notebook(
        self,
        notebook_dir: Path,
        notebook_json: Path,
        result: NotebookLMHistoricalResult,
    ) -> None:
        data = json.loads(notebook_json.read_text(encoding="utf-8"))
        notebook_id = str(data.get("uuid") or notebook_dir.name)
        conversation_id = f"archive-{self.archive_key}_{notebook_id}"
        branch_id = f"{conversation_id}_main"
        captured_at = self.captured_at

        guide = data.get("guide") or {}
        if isinstance(guide, list):
            guide = guide[0] if guide else {}
        if not isinstance(guide, dict):
            guide = {}
        summary = guide.get("summary") if isinstance(guide.get("summary"), str) else None

        local_messages: list[Message] = []
        if summary:
            local_messages.append(
                Message(
                    message_id=f"{conversation_id}_guide_summary",
                    conversation_id=conversation_id,
                    source=SOURCE,
                    sequence=0,
                    role="system",
                    content=summary,
                    model="gemini",
                    created_at=captured_at,
                    account=self.account,
                    branch_id=branch_id,
                )
            )

        chat_path = notebook_dir / "chat.json"
        if chat_path.is_file():
            chat = json.loads(chat_path.read_text(encoding="utf-8"))
            if isinstance(chat, list):
                for chat_index, turn in enumerate(chat):
                    if not isinstance(turn, dict) or turn.get("role") not in {
                        "user",
                        "assistant",
                        "system",
                    }:
                        continue
                    sequence = len(local_messages)
                    raw_id = turn.get("id")
                    message_id = str(raw_id) if raw_id else _stable_id(
                        self.archive_key, notebook_id, "chat", chat_index
                    )
                    raw_timestamp = turn.get("timestamp")
                    try:
                        created_at = pd.Timestamp(raw_timestamp) if raw_timestamp else captured_at
                        if created_at.tzinfo is None:
                            created_at = created_at.tz_localize("UTC")
                        else:
                            created_at = created_at.tz_convert("UTC")
                    except (TypeError, ValueError):
                        created_at = captured_at
                    local_messages.append(
                        Message(
                            message_id=message_id,
                            conversation_id=conversation_id,
                            source=SOURCE,
                            sequence=sequence,
                            role=turn["role"],
                            content=str(turn.get("content") or ""),
                            model="gemini",
                            created_at=created_at,
                            account=self.account,
                            branch_id=branch_id,
                        )
                    )

        first_message_id = local_messages[0].message_id if local_messages else ""
        last_message_id = local_messages[-1].message_id if local_messages else ""
        result.messages.extend(local_messages)
        result.branches.append(
            Branch(
                branch_id=branch_id,
                conversation_id=conversation_id,
                source=SOURCE,
                root_message_id=first_message_id,
                leaf_message_id=last_message_id,
                is_active=True,
                created_at=captured_at,
            )
        )

        for source in data.get("sources") or []:
            if not isinstance(source, dict) or not source.get("uuid"):
                continue
            result.sources.append(
                ProjectDoc(
                    doc_id=str(source["uuid"]),
                    project_id=conversation_id,
                    source=SOURCE,
                    file_name=str(source.get("name") or ""),
                    content="",
                    content_size=0,
                    estimated_token_count=0,
                    created_at=captured_at,
                )
            )

        assets_dir = notebook_dir / "audio"
        if assets_dir.is_dir():
            for asset in sorted(assets_dir.iterdir()):
                if not asset.is_file() or asset.name.startswith("."):
                    continue
                extension = asset.suffix.lower()
                if extension == ".md" and asset.name.endswith("_brief.md"):
                    content = asset.read_text(encoding="utf-8")
                    title = next(
                        (line[2:].strip() for line in content.splitlines()[:7] if line.startswith("# ")),
                        None,
                    )
                    result.notes.append(
                        NotebookLMNote(
                            note_id=asset.stem.removesuffix("_brief"),
                            conversation_id=conversation_id,
                            source=SOURCE,
                            account=self.account,
                            title=title,
                            content=content,
                            kind="brief",
                            source_refs_json=None,
                            created_at=captured_at,
                        )
                    )
                elif extension in _EXT_TO_OUTPUT:
                    output_type, output_name = _EXT_TO_OUTPUT[extension]
                    relative_asset = asset.relative_to(notebook_dir.parent).as_posix()
                    result.outputs.append(
                        NotebookLMOutput(
                            output_id=_stable_id(
                                self.archive_key, notebook_id, "asset", relative_asset
                            ),
                            conversation_id=conversation_id,
                            source=SOURCE,
                            account=self.account,
                            output_type=output_type,
                            output_type_name=output_name,
                            title=None if asset.stem == "unnamed" else asset.stem,
                            status="completed",
                            asset_path=[str(asset)],
                            content=None,
                            source_refs_json=None,
                            created_at=captured_at,
                        )
                    )

        questions = guide.get("questions") or []
        if isinstance(questions, list):
            for index, question in enumerate(questions):
                if not isinstance(question, str):
                    continue
                result.guide_questions.append(
                    NotebookLMGuideQuestion(
                        question_id=f"{conversation_id}_q{index}",
                        conversation_id=conversation_id,
                        source=SOURCE,
                        account=self.account,
                        question_text=question,
                        full_prompt=question,
                        order=index,
                    )
                )

        result.conversations.append(
            Conversation(
                conversation_id=conversation_id,
                source=SOURCE,
                title=str(data.get("title") or notebook_id),
                created_at=captured_at,
                updated_at=captured_at,
                message_count=len(local_messages),
                model="gemini",
                account=self.account,
                mode="chat",
                url=f"https://notebooklm.google.com/notebook/{notebook_id}",
                summary=summary,
                capture_method=HISTORICAL_CAPTURE_METHOD,
            )
        )


def parse_historical_archives(root: Path) -> NotebookLMHistoricalResult:
    """Parse each direct child snapshot using its directory name as provenance."""

    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"configured NotebookLM historical archive root is missing: {root}")

    archive_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    if not archive_dirs:
        raise ValueError(f"configured NotebookLM historical archive root is empty: {root}")

    combined = NotebookLMHistoricalResult()
    for archive_dir in archive_dirs:
        if not any((child / "notebook.json").is_file() for child in archive_dir.iterdir()):
            raise ValueError(f"historical archive has no notebook snapshots: {archive_dir}")
        combined.extend(NotebookLMHistoricalParser(archive_dir.name).parse(archive_dir))
    return combined
