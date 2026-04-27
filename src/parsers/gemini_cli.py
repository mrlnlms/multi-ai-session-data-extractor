# src/parsers/gemini_cli.py
"""Parser para sessoes do Gemini CLI."""

import json
import logging
from pathlib import Path

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message, ToolEvent

logger = logging.getLogger(__name__)


class GeminiCLIParser(BaseParser):
    source_name = "gemini_cli"

    def parse(self, input_path: Path) -> None:
        """Le sessoes JSON de todos os projetos em input_path.

        input_path deve ser a raiz (ex: data/raw/Gemini CLI Data/)
        contendo subdiretorios por projeto, cada um com chats/*.json.
        """
        for project_dir in sorted(input_path.iterdir()):
            if not project_dir.is_dir():
                continue
            chats_dir = project_dir / "chats"
            if not chats_dir.exists():
                continue

            # Resolver nome do projeto
            project_root_file = project_dir / ".project_root"
            if project_root_file.exists():
                project_name = project_root_file.read_text().strip()
            else:
                project_name = project_dir.name

            for session_file in sorted(chats_dir.glob("session-*.json")):
                self._parse_session(session_file, project_name)

    def parse_files(self, files: list[Path]) -> None:
        """Processa apenas a lista de arquivos especificada (uso incremental).

        Infere project_name do path: <project_dir>/chats/<session>.json.
        Se <project_dir>/.project_root existe, usa o conteúdo; senão, usa o nome do dir.
        """
        for session_file in files:
            project_dir = session_file.parent.parent  # .../chats/<file>.json → .../<project_dir>
            project_root_file = project_dir / ".project_root"
            if project_root_file.exists():
                project_name = project_root_file.read_text().strip()
            else:
                project_name = project_dir.name
            self._parse_session(session_file, project_name)

    def _parse_session(self, session_file: Path, project_name: str) -> None:
        data = json.loads(session_file.read_text(encoding="utf-8"))
        messages_data = data.get("messages", [])

        # Filtrar so user e gemini
        content_msgs = [m for m in messages_data if m.get("type") in ("user", "gemini")]
        if not content_msgs:
            return

        session_id = data["sessionId"]
        created_at = self._ts(data.get("startTime"))
        updated_at = self._ts(data.get("lastUpdated"))

        messages = []
        events = []
        seq = 0

        for msg_data in content_msgs:
            seq += 1
            msg_type = msg_data["type"]
            msg_id = msg_data.get("id", f"{session_id}_{seq}")
            timestamp = self._ts(msg_data.get("timestamp"))

            if msg_type == "user":
                content_parts = msg_data.get("content", [])
                if isinstance(content_parts, list):
                    content = "\n\n".join(p.get("text", "") for p in content_parts if isinstance(p, dict))
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
                    content = "\n\n".join(p.get("text", "") for p in content if isinstance(p, dict))

                # Thinking
                thoughts = msg_data.get("thoughts") or []
                thinking = "\n\n".join(
                    f"**{t.get('subject', '')}**: {t.get('description', '')}"
                    for t in thoughts if t.get("description")
                ) or None

                # Tokens
                tokens = msg_data.get("tokens") or {}
                token_count = tokens.get("total")

                # Model
                model = msg_data.get("model")

                # Content types
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
                        metadata_json=json.dumps({
                            k: v for k, v in tc.items()
                            if k not in ("id", "name", "args", "status", "timestamp")
                        }, ensure_ascii=False) if any(
                            k not in ("id", "name", "args", "status", "timestamp") for k in tc
                        ) else None,
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
