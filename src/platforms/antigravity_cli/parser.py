"""Canonical parser for Antigravity CLI (``agy``) local trajectories.

Antigravity stores durable conversation containers in two generations:
legacy encrypted ``conversations/<id>.pb`` files and current per-conversation
SQLite databases. Both are preserved in raw. Current readable transcripts live
under ``brain/<id>/.system_generated/logs/transcript.jsonl``. Legacy PBs can
also have a decoded ``recovered/<id>.trajectory.json`` sidecar produced through
Antigravity's local daemon; the current transcript always takes precedence.
Explicit artifact writes whose trajectory preserves ``ArtifactMetadata`` and
``CodeContent`` are materialized as assistant output assets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import sqlite3
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.parsing.base import BaseParser
from src.schema.models import (
    Branch,
    Asset,
    AssetLink,
    Conversation,
    Message,
    ToolEvent,
    branches_to_df,
    asset_links_to_df,
    assets_to_df,
    conversations_to_df,
    messages_to_df,
    make_asset_link_id,
    tool_events_to_df,
)


logger = logging.getLogger(__name__)


def make_artifact_asset_id(
    conversation_id: str,
    message_id: str,
    tool_index: int,
    content_sha256: str,
) -> str:
    locator = "\x1f".join((conversation_id, message_id, str(tool_index), content_sha256))
    return hashlib.sha256(locator.encode("utf-8")).hexdigest()


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
        self.assets: list[Asset] = []
        self.asset_links: list[AssetLink] = []

    @staticmethod
    def _decoded_string(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        return decoded if isinstance(decoded, str) else value

    @classmethod
    def _artifact_payload(cls, tool_call: Any) -> Optional[tuple[str, str, dict]]:
        if not isinstance(tool_call, dict) or not isinstance(tool_call.get("args"), dict):
            return None
        args = tool_call["args"]
        metadata = args.get("ArtifactMetadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                return None
        if not isinstance(metadata, dict):
            return None
        target = cls._decoded_string(args.get("TargetFile"))
        content = cls._decoded_string(args.get("CodeContent"))
        if not target or content is None:
            return None
        return target, content, metadata

    def _record_artifact(
        self,
        tool_call: Any,
        conversation_id: str,
        message_id: str,
        tool_index: int,
        created_at: pd.Timestamp,
    ) -> Optional[str]:
        payload = self._artifact_payload(tool_call)
        if payload is None or self._input_path is None:
            return None
        target, content, metadata = payload
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        suffix = Path(target).suffix or ".txt"
        out = (
            self._input_path / "_artifacts" / conversation_id
            / f"{message_id.rsplit('_', 1)[-1]}_{tool_index}{suffix}"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            if hashlib.sha256(out.read_bytes()).hexdigest() != digest:
                raise ValueError(f"preserved Antigravity artifact hash mismatch: {out}")
        else:
            out.write_bytes(encoded)
        asset_path = f"raw/Antigravity CLI/_artifacts/{conversation_id}/{out.name}"
        asset_id = make_artifact_asset_id(
            conversation_id, message_id, tool_index, digest
        )
        public_metadata = {
            key: metadata[key]
            for key in ("ArtifactType", "RequestFeedback", "UserFacing")
            if key in metadata
        }
        self.assets.append(Asset(
            asset_id=asset_id, source=self.source_name, account_id=self.account_id,
            asset_kind="artifact", asset_origin="assistant",
            file_name=Path(target).name, mime_type=mimetypes.guess_type(target)[0],
            size_bytes=len(encoded), asset_path=asset_path,
            is_model_generated=True, is_preserved_missing=False,
            is_binary_available=True, created_at=created_at,
            metadata_json=json.dumps(
                {"content_sha256": digest, **public_metadata}, sort_keys=True
            ),
        ))
        self.asset_links.append(AssetLink(
            asset_link_id=make_asset_link_id(
                self.source_name, self.account_id, asset_id, "message", message_id,
                "output", tool_index,
            ),
            source=self.source_name, account_id=self.account_id, asset_id=asset_id,
            object_type="message", object_id=message_id,
            conversation_id=conversation_id, message_id=message_id,
            project_id=None, role="output", ordinal=tool_index,
            content_block_index=None, metadata_json=None,
        ))
        return asset_path

    def parse(self, input_path: Path) -> None:
        """Parse all readable trajectories and retain opaque containers as stubs."""
        input_path = Path(input_path)
        self._input_path = input_path
        self._history = self._load_history(input_path / "history.jsonl")
        self._metadata = self._load_metadata(input_path / "cache" / "conversation_metadata.json")
        self._summaries = self._load_sqlite_summaries(input_path / "conversation_summaries.db")

        brain = input_path / "brain"
        current_ids: set[str] = set()
        if brain.is_dir():
            for transcript in sorted(brain.glob("*/.system_generated/logs/transcript.jsonl")):
                current_ids.add(transcript.parent.parent.parent.name)
                self._parse_transcript(transcript)

        recovered = input_path / "recovered"
        if recovered.is_dir():
            for trajectory in sorted(recovered.glob("*.trajectory.json")):
                conversation_id = trajectory.name.removesuffix(".trajectory.json")
                if conversation_id not in current_ids:
                    self._parse_recovered_trajectory(trajectory)

        self._add_opaque_conversation_stubs(input_path / "conversations")
        self._build_branches()
        from src.capture.cli.preservation import mark_cli_preservation
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
        if normalized in {"DONE", "SUCCESS", "COMPLETED"} or normalized.endswith(("_DONE", "_SUCCESS", "_COMPLETED")):
            return True
        if normalized in {"ERROR", "FAILED", "CANCELLED"} or normalized.endswith(("_ERROR", "_FAILED", "_CANCELLED")):
            return False
        return None

    @staticmethod
    def _first_string(mapping: Any, *keys: str) -> Optional[str]:
        if not isinstance(mapping, dict):
            return None
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value:
                return value
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
                    artifact_path = self._record_artifact(
                        tool_call, conv_id, message_id, tool_idx, timestamp
                    )
                    if artifact_path:
                        messages[-1].asset_paths = [
                            *(messages[-1].asset_paths or []), artifact_path
                        ]
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

    def _parse_recovered_trajectory(self, path: Path) -> None:
        """Parse one daemon-decoded legacy trajectory sidecar."""
        try:
            trajectory = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("  Antigravity CLI: recovered trajectory unreadable %s: %s", path.name, error)
            return
        if not isinstance(trajectory, dict):
            logger.warning("  Antigravity CLI: recovered trajectory is not an object: %s", path.name)
            return
        conv_id = trajectory.get("cascadeId")
        if not isinstance(conv_id, str) or not conv_id:
            conv_id = path.name.removesuffix(".trajectory.json")
        steps = trajectory.get("steps")
        if not isinstance(steps, list):
            logger.warning("  Antigravity CLI: recovered trajectory has no steps: %s", path.name)
            return

        rel = self._relative_path(path)
        if rel:
            self._conv_source_files.setdefault(conv_id, set()).add(rel)
        title, project, description = self._conversation_hints(conv_id)
        model: Optional[str] = None
        generators = trajectory.get("generatorMetadata")
        if isinstance(generators, list) and generators and isinstance(generators[0], dict):
            generator = generators[0]
            model = (
                self._first_string(generator.get("plannerConfig"), "modelName")
                or self._first_string(generator.get("chatModel"), "model")
            )

        messages: list[Message] = []
        events: list[ToolEvent] = []
        timestamps: list[pd.Timestamp] = []
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            raw_kind = step.get("type") if isinstance(step.get("type"), str) else "UNKNOWN"
            kind = raw_kind.removeprefix("CORTEX_STEP_TYPE_")
            status = step.get("status")
            metadata = step.get("metadata") if isinstance(step.get("metadata"), dict) else {}
            timestamp = self._ts(metadata.get("createdAt"))
            if not pd.isna(timestamp):
                timestamps.append(timestamp)
            message_id = f"{conv_id}_legacy_step_{step_index}"

            if kind == "USER_INPUT":
                content = self._first_string(
                    step.get("userInput"), "userResponse", "content", "text", "message"
                )
                if content is not None:
                    messages.append(Message(
                        message_id=message_id, conversation_id=conv_id,
                        source=self.source_name, sequence=len(messages) + 1,
                        role="user", content=content, model=None,
                        created_at=timestamp, account=self.account, content_types="text",
                    ))
                continue

            if kind == "PLANNER_RESPONSE":
                response = step.get("plannerResponse")
                content = self._first_string(response, "content", "response", "text", "message")
                thinking = self._first_string(response, "thinking", "reasoning")
                tool_calls: list[Any] = []
                if isinstance(response, dict):
                    candidate_calls = response.get("toolCalls", response.get("tool_calls"))
                    if isinstance(candidate_calls, list):
                        tool_calls = candidate_calls
                if content is not None or thinking is not None or tool_calls:
                    content_types = ["text"]
                    if thinking:
                        content_types.insert(0, "thinking")
                    if tool_calls:
                        content_types.append("tool_use")
                    messages.append(Message(
                        message_id=message_id, conversation_id=conv_id,
                        source=self.source_name, sequence=len(messages) + 1,
                        role="assistant", content=content or "", model=model,
                        created_at=timestamp, account=self.account, thinking=thinking,
                        content_types=",".join(content_types),
                    ))
                    for tool_index, tool_call in enumerate(tool_calls):
                        artifact_path = self._record_artifact(
                            tool_call, conv_id, message_id, tool_index, timestamp
                        )
                        if artifact_path:
                            messages[-1].asset_paths = [
                                *(messages[-1].asset_paths or []), artifact_path
                            ]
                        tool_name, file_path, command, metadata_json = self._tool_details(tool_call)
                        events.append(ToolEvent(
                            event_id=f"{message_id}_tool_{tool_index}",
                            conversation_id=conv_id, message_id=message_id,
                            source=self.source_name, event_type="tool_call",
                            tool_name=tool_name, file_path=file_path, command=command,
                            success=self._success_from_status(status), metadata_json=metadata_json,
                        ))
                continue

            if kind == "ERROR_MESSAGE":
                error_message = step.get("errorMessage")
                error_payload = error_message.get("error") if isinstance(error_message, dict) else None
                result = self._first_string(
                    error_payload, "userMessage", "message", "errorMessage", "details", "executionError"
                )
                events.append(ToolEvent(
                    event_id=f"{message_id}_event", conversation_id=conv_id,
                    message_id=message_id, source=self.source_name,
                    event_type="error_message", tool_name="ERROR_MESSAGE", success=False,
                    metadata_json=json.dumps({"legacy_type": raw_kind, "status": status}),
                    result=result,
                ))
                continue

            events.append(ToolEvent(
                event_id=f"{message_id}_event", conversation_id=conv_id,
                message_id=message_id, source=self.source_name,
                event_type=kind.lower(), tool_name=kind,
                success=self._success_from_status(status),
                metadata_json=json.dumps({"legacy_type": raw_kind, "status": status}),
            ))

        root_metadata = trajectory.get("metadata") if isinstance(trajectory.get("metadata"), dict) else {}
        root_timestamp = self._ts(root_metadata.get("createdAt"))
        if not pd.isna(root_timestamp):
            timestamps.append(root_timestamp)
        fallback = self._ts(path.stat().st_mtime)
        created_at = min(timestamps) if timestamps else fallback
        updated_at = max(timestamps) if timestamps else fallback
        self.conversations.append(Conversation(
            conversation_id=conv_id, source=self.source_name, title=title,
            created_at=created_at, updated_at=updated_at,
            message_count=len(messages), model=model, account=self.account,
            mode="cli", project=project, summary=description,
            capture_method="legacy_antigravity_daemon",
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
        assets_to_df(self.assets).to_parquet(
            output_dir / "antigravity_cli_assets.parquet", index=False)
        asset_links_to_df(self.asset_links).to_parquet(
            output_dir / "antigravity_cli_asset_links.parquet", index=False)
        return {
            "conversations": len(self.conversations),
            "messages": len(self.messages),
            "tool_events": len(self.events),
            "branches": len(self.branches),
            "assets": len(self.assets),
            "asset_links": len(self.asset_links),
        }
