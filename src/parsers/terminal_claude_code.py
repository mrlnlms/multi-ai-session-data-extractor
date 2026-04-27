"""Parser para sessoes Claude Code salvas como texto do terminal.

Formato: output renderizado do Claude Code CLI com box-drawing characters.
User turns marcados com ❯, assistant turns com ⏺.
Tool events extraidos de blocos como ⏺ Bash(...), ⏺ Read(...), etc.
"""

import logging
import os
import re
import uuid
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message, ToolEvent

logger = logging.getLogger(__name__)

# Pattern for tool use: ⏺ ToolName(content)
TOOL_PATTERN = re.compile(r"^⏺\s+(\w+)\((.+?)\)\s*$")
# Pattern for search-style tool: ⏺ Searched for ...
TOOL_PATTERN_NO_ARGS = re.compile(r"^⏺\s+Searched for\s+(.+)$")
# Pattern for agents: ⏺ N ToolName agents finished
TOOL_PATTERN_AGENTS = re.compile(r"^⏺\s+(\d+)\s+(\w+)\s+agents?\s+finished")


class TerminalClaudeCodeParser(BaseParser):
    source_name = "terminal_claude_code"

    def parse(self, input_path: Path) -> None:
        """Parse all .txt files in the input directory."""
        input_path = Path(input_path)
        txt_files = sorted(input_path.glob("*.txt"))

        for txt_file in txt_files:
            self._parse_file(txt_file)

    def _parse_file(self, file_path: Path) -> None:
        text = file_path.read_text(encoding="utf-8")
        stem = file_path.stem
        conv_id = f"manual_terminal_{stem}"
        file_ts = self._ts(os.path.getmtime(file_path))

        # Parse turns
        turns = self._parse_turns(text)
        if not turns:
            logger.warning(f"Skipping {file_path.name}: no turns found")
            return

        # Build messages and extract tool events
        messages = []
        events = []
        for seq, (role, content) in enumerate(turns, start=1):
            msg_id = str(uuid.uuid4())
            messages.append(Message(
                message_id=msg_id,
                conversation_id=conv_id,
                source="claude_code",
                sequence=seq,
                role=role,
                content=content,
                model=None,
                created_at=file_ts,
                account=self.account,
                content_types="text",
            ))

            # Extract tool events from assistant messages
            if role == "assistant":
                msg_events = self._extract_tool_events(content, conv_id, msg_id)
                events.extend(msg_events)

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source="claude_code",
            title=stem,
            created_at=file_ts,
            updated_at=file_ts,
            message_count=len(messages),
            model=None,
            account=self.account,
            mode="cli",
        ))
        self.messages.extend(messages)
        self.events.extend(events)

    @staticmethod
    def _parse_turns(text: str) -> list[tuple[str, str]]:
        """Parse terminal output into (role, content) tuples.

        ❯ marks user turns, ⏺ marks assistant turns.
        Lines between markers of the same role are concatenated.
        The header box (╭...╰) is skipped.
        """
        lines = text.split("\n")
        turns = []
        current_role = None
        current_lines = []

        # Skip header box
        in_header = False
        content_lines = []
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
                # User turn — flush previous
                if current_role and current_lines:
                    text_content = "\n".join(current_lines).strip()
                    if text_content:
                        turns.append((current_role, text_content))
                current_role = "user"
                # Strip ❯ marker and leading whitespace
                user_text = re.sub(r"^❯\s*", "", stripped)
                current_lines = [user_text] if user_text else []

            elif stripped.startswith("⏺"):
                if current_role == "assistant":
                    # Continue assistant turn — append this line
                    current_lines.append(stripped)
                else:
                    # New assistant turn — flush previous
                    if current_role and current_lines:
                        text_content = "\n".join(current_lines).strip()
                        if text_content:
                            turns.append((current_role, text_content))
                    current_role = "assistant"
                    current_lines = [stripped]

            elif stripped.startswith("⎿") or stripped.startswith("│") or stripped.startswith("├") or stripped.startswith("└"):
                # Tool output continuation — part of assistant turn
                if current_role == "assistant":
                    current_lines.append(line.rstrip())

            elif stripped.startswith("✻"):
                # Completion summary — part of assistant turn
                if current_role == "assistant":
                    current_lines.append(stripped)

            elif current_role:
                # Regular line — continuation of current turn
                current_lines.append(line.rstrip())

        # Flush last turn
        if current_role and current_lines:
            text_content = "\n".join(current_lines).strip()
            if text_content:
                turns.append((current_role, text_content))

        return turns

    @staticmethod
    def _extract_tool_events(content: str, conv_id: str, msg_id: str) -> list[ToolEvent]:
        """Extract tool events from assistant message content."""
        events = []
        for line in content.split("\n"):
            stripped = line.strip()

            # Match ⏺ ToolName(args)
            match = TOOL_PATTERN.match(stripped)
            if match:
                tool_name = match.group(1)
                args = match.group(2)
                events.append(ToolEvent(
                    event_id=str(uuid.uuid4()),
                    conversation_id=conv_id,
                    message_id=msg_id,
                    source="claude_code",
                    event_type="tool_call",
                    tool_name=tool_name,
                    command=args if tool_name == "Bash" else None,
                    file_path=args if tool_name in ("Read", "Write", "Edit") else None,
                ))
                continue

            # Match ⏺ Searched for N patterns
            match = TOOL_PATTERN_NO_ARGS.match(stripped)
            if match:
                events.append(ToolEvent(
                    event_id=str(uuid.uuid4()),
                    conversation_id=conv_id,
                    message_id=msg_id,
                    source="claude_code",
                    event_type="tool_call",
                    tool_name="Search",
                ))
                continue

        return events
