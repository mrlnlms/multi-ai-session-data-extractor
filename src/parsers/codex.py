# src/parsers/codex.py
"""Parser para sessoes do Codex CLI."""

import json
import logging
from pathlib import Path

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message, ToolEvent

logger = logging.getLogger(__name__)


class CodexParser(BaseParser):
    source_name = "codex"

    def parse(self, input_path: Path) -> None:
        """Le sessoes JSONL de input_path (estrutura: year/month/day/rollout-*.jsonl)."""
        for session_file in sorted(input_path.rglob("rollout-*.jsonl")):
            self._parse_session(session_file)

    def parse_files(self, files: list[Path]) -> None:
        """Processa apenas a lista de arquivos especificada (uso incremental)."""
        for session_file in files:
            self._parse_session(session_file)

    def _parse_session(self, session_file: Path) -> None:
        lines = session_file.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(line) for line in lines if line.strip()]

        meta = None
        model = None
        user_msgs = []
        agent_msgs = []
        reasoning_parts = []
        function_calls = {}
        exec_ends = {}
        timestamps = []

        for evt in events:
            ts = evt.get("timestamp")
            if ts:
                timestamps.append(ts)
            etype = evt.get("type")
            payload = evt.get("payload", {})

            if etype == "session_meta":
                meta = payload
            elif etype == "turn_context":
                model = model or payload.get("model")
            elif etype == "event_msg":
                ptype = payload.get("type")
                if ptype == "user_message":
                    # Flush pending reasoning to previous agent msg
                    if agent_msgs and reasoning_parts:
                        agent_msgs[-1]["_thinking"] = "\n\n".join(reasoning_parts)
                        reasoning_parts = []
                    user_msgs.append({"content": payload.get("message", ""), "ts": ts})
                elif ptype == "agent_message":
                    # Attach accumulated reasoning
                    thinking = "\n\n".join(reasoning_parts) if reasoning_parts else None
                    reasoning_parts = []
                    agent_msgs.append({"content": payload.get("message", ""), "ts": ts, "_thinking": thinking})
                elif ptype == "agent_reasoning":
                    reasoning_parts.append(payload.get("text", ""))
                elif ptype == "exec_command_end":
                    call_id = payload.get("call_id")
                    if call_id:
                        exec_ends[call_id] = payload
            elif etype == "response_item":
                ptype = payload.get("type")
                if ptype == "function_call":
                    call_id = payload.get("call_id")
                    if call_id:
                        function_calls[call_id] = {"payload": payload, "ts": ts}

        # Flush trailing reasoning
        if agent_msgs and reasoning_parts:
            agent_msgs[-1]["_thinking"] = "\n\n".join(reasoning_parts)

        if not meta or (not user_msgs and not agent_msgs):
            return

        session_id = meta["id"]
        cwd = meta.get("cwd", "")

        # Build messages interleaved by timestamp
        all_msgs = []
        for m in user_msgs:
            all_msgs.append({"role": "user", **m})
        for m in agent_msgs:
            all_msgs.append({"role": "assistant", **m})
        all_msgs.sort(key=lambda m: m["ts"] or "")

        messages = []
        for seq, m in enumerate(all_msgs, 1):
            ct_parts = ["text"]
            if m.get("_thinking"):
                ct_parts.insert(0, "thinking")

            messages.append(Message(
                message_id=f"{session_id}_{seq}",
                conversation_id=session_id,
                source=self.source_name,
                sequence=seq,
                role=m["role"],
                content=m["content"],
                model=model if m["role"] == "assistant" else None,
                created_at=self._ts(m["ts"]),
                account=self.account,
                thinking=m.get("_thinking"),
                content_types=",".join(ct_parts),
            ))

        # Tool events
        tool_events = []
        for call_id, fc in function_calls.items():
            payload = fc["payload"]
            args_str = payload.get("arguments", "{}")
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                args = {}

            # Enriquecer com exec_command_end se disponivel
            exec_end = exec_ends.get(call_id)
            duration_ms = None
            success = None
            command = args.get("cmd")

            if exec_end:
                dur = exec_end.get("duration", {})
                duration_ms = dur.get("secs", 0) * 1000 + dur.get("nanos", 0) // 1_000_000
                success = exec_end.get("exit_code") == 0
                command = command or exec_end.get("command")

            tool_events.append(ToolEvent(
                event_id=call_id,
                conversation_id=session_id,
                message_id=f"{session_id}_tool_{call_id}",
                source=self.source_name,
                event_type="tool_call",
                tool_name=payload.get("name", ""),
                file_path=args.get("file_path"),
                command=command,
                duration_ms=duration_ms,
                success=success,
            ))

        self.conversations.append(Conversation(
            conversation_id=session_id,
            source=self.source_name,
            title=None,
            created_at=self._ts(timestamps[0]) if timestamps else None,
            updated_at=self._ts(timestamps[-1]) if timestamps else None,
            message_count=len(messages),
            model=model,
            account=self.account,
            mode="cli",
            project=cwd,
        ))
        self.messages.extend(messages)
        self.events.extend(tool_events)
