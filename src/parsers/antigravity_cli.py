"""Canonical parser for Antigravity CLI (``agy``) local trajectories.

Antigravity stores durable conversation containers in two generations:
legacy encrypted ``conversations/<id>.pb`` files and current per-conversation
SQLite databases. Both are preserved in raw. The readable, lossless transcript
for supported conversations is ``brain/<id>/.system_generated/logs/``
``transcript.jsonl``; this parser deliberately uses it instead of depending on
the undocumented protobuf BLOBs in SQLite.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import (
    Branch,
    Conversation,
    Message,
    ToolEvent,
    branches_to_df,
    conversations_to_df,
    messages_to_df,
    tool_events_to_df,
)


logger = logging.getLogger(__name__)


class AntigravityCLIParser(BaseParser):
    """Parse Antigravity CLI JSONL trajectories into the canonical v3 schema."""

    source_name = "antigravity_cli"

    def __init__(self, account: Optional[str] = None):
        super().__init__(account=account)
        self.branches: list[Branch] = []
        self._conv_source_files: dict[str, set[str]] = {}
        self._input_path: Optional[Path] = None
        self._history: dict[str, dict[str, Any]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._summaries: dict[str, dict[str, Any]] = {}

    def reset(self):
        super().reset()
        self.branches = []
        self._conv_source_files = {}
        self._input_path = None
        self._history = {}
        self._metadata = {}
        self._summaries = {}

    def parse(self, input_path: Path) -> None:
        """Parse all readable trajectories and retain opaque containers as stubs."""
        input_path = Path(input_path)
        self._input_path = input_path
        self._history = self._load_history(input_path / "history.jsonl")
        self._metadata = self._load_metadata(input_path / "cache" / "conversation_metadata.json")
        self._summaries = self._load_sqlite_summaries(input_path / "conversation_summaries.db")

        brain = input_path / "brain"
        if brain.is_dir():
            for transcript in sorted(brain.glob("*/.system_generated/logs/transcript.jsonl")):
                self._parse_transcript(transcript)

        self._add_opaque_conversation_stubs(input_path / "conversations")
        self._build_branches()
        from src.extractors.cli.preservation import mark_cli_preservation
        mark_cli_preservation(self)

    def _relative_path(self, path: Path) -> Optional[str]:
        if self._input_path is None:
            return None
        try:
            return str(path.relative_to(self._input_path))
        except ValueError:
            return None

    @staticmethod
    def _load_history(path: Path) -> dict[str, dict[str, Any]]:
        """Load latest title/workspace hints keyed by conversation ID."""
        out: dict[str, dict[str, Any]] = {}
        if not path.exists():
            return out
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict) or not isinstance(record.get("conversationId"), str):
                        continue
                    conv_id = record["conversationId"]
                    old = out.get(conv_id)
                    if old is None or str(record.get("timestamp", "")) >= str(old.get("timestamp", "")):
                        out[conv_id] = record
        except OSError as e:
            logger.warning("  Antigravity CLI: history read failed: %s", e)
        return out

    @staticmethod
    def _load_metadata(path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("  Antigravity CLI: metadata read failed: %s", e)
            return {}
        conversations = data.get("conversations") if isinstance(data, dict) else None
        return conversations if isinstance(conversations, dict) else {}

    @staticmethod
    def _load_sqlite_summaries(path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        try:
            with sqlite3.connect(f"file://{path}?mode=ro", uri=True, timeout=2) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT conversation_id, title, preview, last_modified_time, workspace_uris "
                    "FROM conversation_summaries"
                ).fetchall()
            return {row["conversation_id"]: dict(row) for row in rows if row["conversation_id"]}
        except sqlite3.Error as e:
            logger.warning("  Antigravity CLI: summaries database unreadable: %s", e)
            return {}

    def _conversation_hints(self, conv_id: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        summary = self._summaries.get(conv_id, {})
        history = self._history.get(conv_id, {})
        metadata = self._metadata.get(conv_id, {})
        title = summary.get("title") or history.get("display")
        project = history.get("workspace") or summary.get("workspace_uris")
        description = summary.get("preview") or metadata.get("summary")
        return (
            title if isinstance(title, str) and title else None,
            project if isinstance(project, str) and project else None,
            description if isinstance(description, str) and description else None,
        )

    @staticmethod
    def _success_from_status(status: Any) -> Optional[bool]:
        if not isinstance(status, str):
            return None
        normalized = status.upper()
        if normalized in {"DONE", "SUCCESS", "COMPLETED"}:
            return True
        if normalized in {"ERROR", "FAILED", "CANCELLED"}:
            return False
        return None

    @staticmethod
    def _tool_details(tool_call: Any) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Return tool name, file path, command and JSON args for one tool call."""
        if not isinstance(tool_call, dict):
            return None, None, None, None
        name = tool_call.get("name")
        args = tool_call.get("args")
        if not isinstance(args, dict):
            return name if isinstance(name, str) else None, None, None, json.dumps(args, ensure_ascii=False)
        file_path = args.get("file_path") or args.get("path") or args.get("dir_path")
        command = args.get("command")
        return (
            name if isinstance(name, str) else None,
            file_path if isinstance(file_path, str) else None,
            command if isinstance(command, str) else None,
            json.dumps(args, ensure_ascii=False),
        )

    def _parse_transcript(self, path: Path) -> None:
        conv_id = path.parent.parent.parent.name
        rel = self._relative_path(path)
        if rel:
            self._conv_source_files.setdefault(conv_id, set()).add(rel)
        records: list[dict[str, Any]] = []
        try:
            with path.open(encoding="utf-8") as f:
                for line_number, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("  Antigravity CLI: invalid JSONL %s:%d", path.name, line_number)
                        continue
                    if isinstance(record, dict):
                        records.append(record)
        except OSError as e:
            logger.warning("  Antigravity CLI: transcript read failed %s: %s", path, e)
            return

        title, project, description = self._conversation_hints(conv_id)
        messages: list[Message] = []
        events: list[ToolEvent] = []
        timestamps: list[pd.Timestamp] = []
        for record_idx, record in enumerate(records):
            step_index = record.get("step_index", record_idx)
            if not isinstance(step_index, int):
                step_index = record_idx
            timestamp = self._ts(record.get("created_at"))
            if not pd.isna(timestamp):
                timestamps.append(timestamp)
            kind = record.get("type") if isinstance(record.get("type"), str) else "UNKNOWN"
            source = record.get("source")
            content = record.get("content") if isinstance(record.get("content"), str) else ""
            thinking = record.get("thinking") if isinstance(record.get("thinking"), str) else None
            message_id = f"{conv_id}_step_{step_index}"

            if kind == "USER_INPUT" and source == "USER_EXPLICIT":
                messages.append(Message(
                    message_id=message_id,
                    conversation_id=conv_id,
                    source=self.source_name,
                    sequence=len(messages) + 1,
                    role="user",
                    content=content,
                    model=None,
                    created_at=timestamp,
                    account=self.account,
                    content_types="text",
                ))
                continue

            if kind == "PLANNER_RESPONSE" and source == "MODEL":
                tool_calls = record.get("tool_calls") if isinstance(record.get("tool_calls"), list) else []
                content_types = ["text"]
                if thinking:
                    content_types.insert(0, "thinking")
                if tool_calls:
                    content_types.append("tool_use")
                messages.append(Message(
                    message_id=message_id,
                    conversation_id=conv_id,
                    source=self.source_name,
                    sequence=len(messages) + 1,
                    role="assistant",
                    content=content,
                    model=None,
                    created_at=timestamp,
                    account=self.account,
                    thinking=thinking,
                    content_types=",".join(content_types),
                ))
                for tool_idx, tool_call in enumerate(tool_calls):
                    tool_name, file_path, command, metadata_json = self._tool_details(tool_call)
                    events.append(ToolEvent(
                        event_id=f"{message_id}_tool_{tool_idx}",
                        conversation_id=conv_id,
                        message_id=message_id,
                        source=self.source_name,
                        event_type="tool_call",
                        tool_name=tool_name,
                        file_path=file_path,
                        command=command,
                        success=self._success_from_status(record.get("status")),
                        metadata_json=metadata_json,
                    ))
                continue

            if kind != "CONVERSATION_HISTORY":
                events.append(ToolEvent(
                    event_id=f"{conv_id}_step_{step_index}_event",
                    conversation_id=conv_id,
                    message_id=message_id,
                    source=self.source_name,
                    event_type=kind.lower(),
                    tool_name=kind,
                    success=self._success_from_status(record.get("status")),
                    metadata_json=json.dumps({
                        key: value for key, value in record.items()
                        if key not in {"content", "thinking", "tool_calls"}
                    }, ensure_ascii=False),
                    result=content or None,
                ))

        if not records:
            return
        created_at = min(timestamps) if timestamps else self._ts(path.stat().st_mtime)
        updated_at = max(timestamps) if timestamps else created_at
        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=self.source_name,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            message_count=len(messages),
            model=None,
            account=self.account,
            mode="cli",
            project=project,
            summary=description,
        ))
        self.messages.extend(messages)
        self.events.extend(events)

    def _add_opaque_conversation_stubs(self, conversations_dir: Path) -> None:
        """Represent preserved containers that have no readable trajectory yet."""
        if not conversations_dir.is_dir():
            return
        known = {conversation.conversation_id for conversation in self.conversations}
        for artifact in sorted(conversations_dir.iterdir()):
            if not artifact.is_file() or artifact.suffix not in (".db", ".pb"):
                continue
            conv_id = artifact.stem
            rel = self._relative_path(artifact)
            if rel:
                self._conv_source_files.setdefault(conv_id, set()).add(rel)
            if conv_id in known:
                continue
            title, project, description = self._conversation_hints(conv_id)
            modified = self._ts(artifact.stat().st_mtime)
            self.conversations.append(Conversation(
                conversation_id=conv_id,
                source=self.source_name,
                title=title,
                created_at=modified,
                updated_at=modified,
                message_count=0,
                model=None,
                account=self.account,
                mode="cli",
                project=project,
                summary=description,
            ))

    def _build_branches(self) -> None:
        messages_by_conv: dict[str, list[Message]] = {}
        for message in self.messages:
            messages_by_conv.setdefault(message.conversation_id, []).append(message)
        for conversation in self.conversations:
            messages = messages_by_conv.get(conversation.conversation_id, [])
            self.branches.append(Branch(
                branch_id=f"{conversation.conversation_id}_main",
                conversation_id=conversation.conversation_id,
                source=self.source_name,
                root_message_id=messages[0].message_id if messages else "",
                leaf_message_id=messages[-1].message_id if messages else "",
                is_active=True,
                created_at=conversation.created_at,
            ))

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def write_parquets(self, output_dir: Path) -> dict[str, int]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        conversations_to_df(self.conversations).to_parquet(
            output_dir / "antigravity_cli_conversations.parquet", index=False)
        messages_df = messages_to_df(self.messages)
        messages_df.to_parquet(output_dir / "antigravity_cli_messages.parquet", index=False)
        tool_events_to_df(self.events).to_parquet(
            output_dir / "antigravity_cli_tool_events.parquet", index=False)
        branches_to_df(self.branches).to_parquet(
            output_dir / "antigravity_cli_branches.parquet", index=False)
        return {
            "conversations": len(self.conversations),
            "messages": len(self.messages),
            "tool_events": len(self.events),
            "branches": len(self.branches),
        }
