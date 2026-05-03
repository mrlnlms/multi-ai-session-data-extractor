"""Parser canonico v3 do Gemini CLI.

Le sessoes JSON de `data/raw/Gemini CLI/<project_hash>/chats/session-*.json`.

Schema empirico (JSON, NAO JSONL como Codex/Claude Code):
- `messages` array com type ∈ {user, gemini, info}
- `info` messages sao filtradas (sistema, nao chat)
- `thoughts` array → thinking (formatado "**subject**: description")
- `tokens.total` → token_count
- `toolCalls` → ToolEvent (status='success' → success=True)
- `.project_root` file resolve nome do projeto (senao usa dir name)

Output: data/processed/Gemini CLI/{gemini_cli_conversations,messages,
tool_events,branches}.parquet.

Branches: 1 _main por Conversation.
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


class GeminiCLIParser(BaseParser):
    source_name = "gemini_cli"

    def __init__(self, account: Optional[str] = None):
        super().__init__(account=account)
        self.branches: list[Branch] = []

    def reset(self):
        super().reset()
        self.branches = []

    def parse(self, input_path: Path) -> None:
        """Le sessoes JSON de todos os projetos em input_path.

        input_path = raiz (ex: data/raw/Gemini CLI/) com subdirs por projeto,
        cada um com chats/*.json.
        """
        input_path = Path(input_path)
        for project_dir in sorted(input_path.iterdir()):
            if not project_dir.is_dir():
                continue
            chats_dir = project_dir / "chats"
            if not chats_dir.exists():
                continue
            project_name = self._resolve_project_name(project_dir)
            for session_file in sorted(chats_dir.glob("session-*.json")):
                self._parse_session(session_file, project_name)
        self._build_branches()

    def parse_files(self, files: list[Path]) -> None:
        """Processa lista especifica (uso incremental). Infere project do path."""
        for session_file in files:
            project_dir = session_file.parent.parent  # .../chats/<file>.json → .../<project_dir>
            project_name = self._resolve_project_name(project_dir)
            self._parse_session(session_file, project_name)
        self._build_branches()

    @staticmethod
    def _resolve_project_name(project_dir: Path) -> str:
        """Le .project_root se existir, senao usa nome do dir."""
        project_root_file = project_dir / ".project_root"
        if project_root_file.exists():
            try:
                return project_root_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        return project_dir.name

    def _build_branches(self) -> None:
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

    def _parse_session(self, session_file: Path, project_name: str) -> None:
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"  {session_file}: falha ao ler: {e}")
            return

        messages_data = data.get("messages", [])
        # Filtrar so user e gemini (info messages sao sistema)
        content_msgs = [m for m in messages_data if m.get("type") in ("user", "gemini")]
        if not content_msgs:
            return

        session_id = data.get("sessionId")
        if not session_id:
            return
        created_at = self._ts(data.get("startTime"))
        updated_at = self._ts(data.get("lastUpdated"))

        messages: list[Message] = []
        events: list[ToolEvent] = []
        seq = 0

        for msg_data in content_msgs:
            seq += 1
            msg_type = msg_data["type"]
            msg_id = msg_data.get("id", f"{session_id}_{seq}")
            timestamp = self._ts(msg_data.get("timestamp"))

            if msg_type == "user":
                content_parts = msg_data.get("content", [])
                if isinstance(content_parts, list):
                    content = "\n\n".join(
                        p.get("text", "") for p in content_parts if isinstance(p, dict)
                    )
                else:
                    content = str(content_parts)

                messages.append(Message(
                    message_id=msg_id,
                    conversation_id=session_id,
                    source=self.source_name,
                    sequence=seq,
                    role="user",
                    content=content,
                    model=None,
                    created_at=timestamp,
                    account=self.account,
                    content_types="text",
                ))

            elif msg_type == "gemini":
                content = msg_data.get("content", "")
                if isinstance(content, list):
                    content = "\n\n".join(
                        p.get("text", "") for p in content if isinstance(p, dict)
                    )

                # Thinking (thoughts → "**subject**: description")
                thoughts = msg_data.get("thoughts") or []
                thinking = "\n\n".join(
                    f"**{t.get('subject', '')}**: {t.get('description', '')}"
                    for t in thoughts if t.get("description")
                ) or None

                tokens = msg_data.get("tokens") or {}
                token_count = tokens.get("total")
                model = msg_data.get("model")

                tool_calls = msg_data.get("toolCalls") or []
                ct_parts = ["text"]
                if thinking:
                    ct_parts.insert(0, "thinking")
                if tool_calls:
                    ct_parts.append("tool_use")

                messages.append(Message(
                    message_id=msg_id,
                    conversation_id=session_id,
                    source=self.source_name,
                    sequence=seq,
                    role="assistant",
                    content=content,
                    model=model,
                    created_at=timestamp,
                    account=self.account,
                    token_count=token_count,
                    thinking=thinking,
                    content_types=",".join(ct_parts),
                ))

                # Tool events
                for tc_idx, tc in enumerate(tool_calls):
                    args = tc.get("args") or {}
                    metadata_keys = {"id", "name", "args", "status", "timestamp"}
                    extra_keys = [k for k in tc if k not in metadata_keys]
                    metadata_json = json.dumps(
                        {k: tc[k] for k in extra_keys}, ensure_ascii=False,
                    ) if extra_keys else None
                    events.append(ToolEvent(
                        event_id=tc.get("id", f"{msg_id}_tool_{tc_idx}"),
                        conversation_id=session_id,
                        message_id=msg_id,
                        source=self.source_name,
                        event_type="tool_call",
                        tool_name=tc.get("name", ""),
                        file_path=args.get("file_path") or args.get("dir_path"),
                        command=args.get("command"),
                        success=tc.get("status") == "success" if tc.get("status") else None,
                        metadata_json=metadata_json,
                    ))

        self.conversations.append(Conversation(
            conversation_id=session_id,
            source=self.source_name,
            title=None,
            created_at=created_at,
            updated_at=updated_at,
            message_count=len(messages),
            model=next((m.model for m in messages if m.model), None),
            account=self.account,
            mode="cli",
            project=project_name,
        ))
        self.messages.extend(messages)
        self.events.extend(events)

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def write_parquets(self, output_dir: Path) -> dict[str, int]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        conversations_to_df(self.conversations).to_parquet(
            output_dir / "gemini_cli_conversations.parquet", index=False)
        messages_to_df(self.messages).to_parquet(
            output_dir / "gemini_cli_messages.parquet", index=False)
        tool_events_to_df(self.events).to_parquet(
            output_dir / "gemini_cli_tool_events.parquet", index=False)
        branches_to_df(self.branches).to_parquet(
            output_dir / "gemini_cli_branches.parquet", index=False)
        return {
            "conversations": len(self.conversations),
            "messages": len(self.messages),
            "tool_events": len(self.events),
            "branches": len(self.branches),
        }
