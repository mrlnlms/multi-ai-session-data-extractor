"""Parser canonico v3 do Codex CLI.

Le sessoes JSONL de `data/raw/Codex/<year>/<month>/<day>/rollout-*.jsonl`.

Schema empirico:
- Eventos sequenciais: session_meta, turn_context, event_msg, response_item
- `session_meta`: id (= conversation_id), cwd, model_provider
- `turn_context`: model
- `event_msg.user_message` / `agent_message`: conteudo de chat
- `event_msg.agent_reasoning`: thinking (acumulado e attached a proxima agent_message)
- `event_msg.exec_command_end`: enriquece tool event com duration_ms + success
- `response_item.function_call`: tool_use, correlacionado com exec_command_end via call_id

Output: data/processed/Codex/{codex_conversations,messages,tool_events,branches}.parquet.

Branches: 1 _main por Conversation (Codex nao tem fork).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

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


class CodexParser(BaseParser):
    source_name = "codex"

    def __init__(self, account: Optional[str] = None):
        super().__init__(account=account)
        self.branches: list[Branch] = []

    def reset(self):
        super().reset()
        self.branches = []

    def parse(self, input_path: Path) -> None:
        """Le todas sessoes em year/month/day/rollout-*.jsonl."""
        input_path = Path(input_path)
        for session_file in sorted(input_path.rglob("rollout-*.jsonl")):
            self._parse_session(session_file)
        self._build_branches()

    def parse_files(self, files: list[Path]) -> None:
        """Processa apenas a lista de arquivos especificada (uso incremental)."""
        for session_file in files:
            self._parse_session(session_file)
        self._build_branches()

    def _build_branches(self) -> None:
        """Gera 1 Branch <conv>_main por Conversation."""
        existing = {b.conversation_id for b in self.branches}
        msgs_by_conv: dict[str, list[Message]] = {}
        for m in self.messages:
            msgs_by_conv.setdefault(m.conversation_id, []).append(m)

        for conv in self.conversations:
            if conv.conversation_id in existing:
                continue
            conv_msgs = sorted(
                msgs_by_conv.get(conv.conversation_id, []),
                key=lambda m: m.sequence,
            )
            root_id = conv_msgs[0].message_id if conv_msgs else ""
            leaf_id = conv_msgs[-1].message_id if conv_msgs else ""
            self.branches.append(Branch(
                branch_id=f"{conv.conversation_id}_main",
                conversation_id=conv.conversation_id,
                source=self.source_name,
                root_message_id=root_id,
                leaf_message_id=leaf_id,
                is_active=True,
                created_at=conv.created_at if conv.created_at is not None else pd.Timestamp.now(tz="UTC"),
            ))

    def _parse_session(self, session_file: Path) -> None:
        try:
            text = session_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"  {session_file}: falha ao ler: {e}")
            return
        events = []
        for line in text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        meta = None
        model = None
        user_msgs = []
        agent_msgs = []
        reasoning_parts: list[str] = []
        function_calls: dict[str, dict] = {}
        exec_ends: dict[str, dict] = {}
        timestamps = []

        for evt in events:
            ts = evt.get("timestamp")
            if ts:
                timestamps.append(ts)
            etype = evt.get("type")
            payload = evt.get("payload", {}) or {}

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
                    agent_msgs.append({
                        "content": payload.get("message", ""),
                        "ts": ts,
                        "_thinking": thinking,
                    })
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

        # Tool events (function_call enriquecido com exec_command_end)
        tool_events = []
        for call_id, fc in function_calls.items():
            payload = fc["payload"]
            args_str = payload.get("arguments", "{}")
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                args = {}

            exec_end = exec_ends.get(call_id)
            duration_ms = None
            success = None
            command = args.get("cmd")

            if exec_end:
                dur = exec_end.get("duration", {}) or {}
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

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def write_parquets(self, output_dir: Path) -> dict[str, int]:
        """Escreve 4 parquets canonicos. Idempotente."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        conversations_to_df(self.conversations).to_parquet(
            output_dir / "codex_conversations.parquet", index=False)
        messages_to_df(self.messages).to_parquet(
            output_dir / "codex_messages.parquet", index=False)
        tool_events_to_df(self.events).to_parquet(
            output_dir / "codex_tool_events.parquet", index=False)
        branches_to_df(self.branches).to_parquet(
            output_dir / "codex_branches.parquet", index=False)
        return {
            "conversations": len(self.conversations),
            "messages": len(self.messages),
            "tool_events": len(self.events),
            "branches": len(self.branches),
        }
