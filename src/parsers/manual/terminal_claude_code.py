"""Parser pra sessoes Claude Code salvas como texto do terminal.

Formato: output renderizado do CC CLI com box-drawing characters.
- ❯ marca user turns
- ⏺ marca assistant turns
- ⎿/│/├/└ tool output continuation
- ✻ completion summary

source = 'claude_code' (mesmo do extractor automatizado)
capture_method = 'manual_terminal_cc'
"""

from __future__ import annotations

import logging
import os
import re
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import (
    Branch,
    Conversation,
    Message,
    ToolEvent,
)


logger = logging.getLogger(__name__)


# Pattern for tool use: ⏺ ToolName(content)
TOOL_PATTERN = re.compile(r"^⏺\s+(\w+)\((.+?)\)\s*$")
TOOL_PATTERN_NO_ARGS = re.compile(r"^⏺\s+Searched for\s+(.+)$")
TOOL_PATTERN_AGENTS = re.compile(r"^⏺\s+(\d+)\s+(\w+)\s+agents?\s+finished")


CAPTURE_METHOD = "manual_terminal_cc"
SOURCE = "claude_code"


class TerminalClaudeCodeParser(BaseParser):
    source_name = "terminal_claude_code"

    def __init__(self, account: Optional[str] = None):
        super().__init__(account=account)
        self.branches: list[Branch] = []

    def reset(self):
        super().reset()
        self.branches = []

    def parse(self, input_path: Path) -> None:
        input_path = Path(input_path)
        for txt_file in sorted(input_path.glob("*.txt")):
            self._parse_file(txt_file)
        self._build_branches()

    def _build_branches(self) -> None:
        msgs_by_conv: dict[str, list[Message]] = {}
        for m in self.messages:
            msgs_by_conv.setdefault(m.conversation_id, []).append(m)
        for conv in self.conversations:
            msgs = sorted(msgs_by_conv.get(conv.conversation_id, []), key=lambda m: m.sequence)
            root_id = msgs[0].message_id if msgs else ""
            leaf_id = msgs[-1].message_id if msgs else ""
            self.branches.append(Branch(
                branch_id=f"{conv.conversation_id}_main",
                conversation_id=conv.conversation_id,
                source=conv.source,
                root_message_id=root_id,
                leaf_message_id=leaf_id,
                is_active=True,
                created_at=conv.created_at if conv.created_at is not None else pd.Timestamp.now(tz="UTC"),
            ))

    def _parse_file(self, file_path: Path) -> None:
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"  {file_path}: falha ao ler: {e}")
            return
        stem = file_path.stem
        conv_id = f"manual_terminal_{stem}"
        file_ts = self._ts(os.path.getmtime(file_path))

        turns = self._parse_turns(text)
        if not turns:
            logger.warning(f"  {file_path.name}: sem turnos detectados")
            return

        messages = []
        events = []
        for seq, (role, content) in enumerate(turns, start=1):
            msg_id = str(uuid_lib.uuid4())
            messages.append(Message(
                message_id=msg_id,
                conversation_id=conv_id,
                source=SOURCE,
                sequence=seq,
                role=role,
                content=content,
                model=None,
                created_at=file_ts,
                account=self.account,
                content_types="text",
            ))
            if role == "assistant":
                events.extend(self._extract_tool_events(content, conv_id, msg_id))

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=SOURCE,
            title=stem,
            created_at=file_ts,
            updated_at=file_ts,
            message_count=len(messages),
            model=None,
            account=self.account,
            mode="cli",
            capture_method=CAPTURE_METHOD,
        ))
        self.messages.extend(messages)
        self.events.extend(events)

    @staticmethod
    def _parse_turns(text: str) -> list[tuple[str, str]]:
        """❯ user, ⏺ assistant, header box ╭...╰ ignorado."""
        lines = text.split("\n")
        turns: list[tuple[str, str]] = []
        current_role: Optional[str] = None
        current_lines: list[str] = []

        in_header = False
        content_lines: list[str] = []
        for line in lines:
            if line.startswith("╭"):
                in_header = True
                continue
            if in_header:
                if line.startswith("╰"):
                    in_header = False
                continue
            content_lines.append(line)

        for line in content_lines:
            stripped = line.strip()

            if stripped.startswith("❯"):
                if current_role and current_lines:
                    text_content = "\n".join(current_lines).strip()
                    if text_content:
                        turns.append((current_role, text_content))
                current_role = "user"
                user_text = re.sub(r"^❯\s*", "", stripped)
                current_lines = [user_text] if user_text else []

            elif stripped.startswith("⏺"):
                if current_role == "assistant":
                    current_lines.append(stripped)
                else:
                    if current_role and current_lines:
                        text_content = "\n".join(current_lines).strip()
                        if text_content:
                            turns.append((current_role, text_content))
                    current_role = "assistant"
                    current_lines = [stripped]

            elif stripped.startswith("⎿") or stripped.startswith("│") or stripped.startswith("├") or stripped.startswith("└"):
                if current_role == "assistant":
                    current_lines.append(line.rstrip())

            elif stripped.startswith("✻"):
                if current_role == "assistant":
                    current_lines.append(stripped)

            elif current_role:
                current_lines.append(line.rstrip())

        if current_role and current_lines:
            text_content = "\n".join(current_lines).strip()
            if text_content:
                turns.append((current_role, text_content))

        return turns

    @staticmethod
    def _extract_tool_events(content: str, conv_id: str, msg_id: str) -> list[ToolEvent]:
        events: list[ToolEvent] = []
        for line in content.split("\n"):
            stripped = line.strip()

            match = TOOL_PATTERN.match(stripped)
            if match:
                tool_name = match.group(1)
                args = match.group(2)
                events.append(ToolEvent(
                    event_id=str(uuid_lib.uuid4()),
                    conversation_id=conv_id,
                    message_id=msg_id,
                    source=SOURCE,
                    event_type="tool_call",
                    tool_name=tool_name,
                    command=args if tool_name == "Bash" else None,
                    file_path=args if tool_name in ("Read", "Write", "Edit") else None,
                ))
                continue

            match = TOOL_PATTERN_NO_ARGS.match(stripped)
            if match:
                events.append(ToolEvent(
                    event_id=str(uuid_lib.uuid4()),
                    conversation_id=conv_id,
                    message_id=msg_id,
                    source=SOURCE,
                    event_type="tool_call",
                    tool_name="Search",
                ))

        return events
