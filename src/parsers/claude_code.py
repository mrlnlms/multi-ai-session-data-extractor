# src/parsers/claude_code.py
"""Parser para sessoes do Claude Code."""

import json
import logging
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message, ToolEvent

# Metadados de sessao ficam em ~/.claude/usage-data/session-meta/<uuid>.json
# Mesmo quando o JSONL raiz some, o meta geralmente sobrevive (first_prompt, stats)
_SESSION_META_DIR = Path.home() / ".claude" / "usage-data" / "session-meta"

logger = logging.getLogger(__name__)


class ClaudeCodeParser(BaseParser):
    source_name = "claude_code"

    def parse(self, input_path: Path) -> None:
        """Le sessoes JSONL de todos os projetos em input_path.

        input_path deve conter subdiretorios por projeto (formato: -Users-xxx-Desktop-project/).
        Cada diretorio contem:
          - *.jsonl (sessoes principais)
          - {session-uuid}/subagents/*.jsonl (subagents)

        Sessoes orfas (subagents sem JSONL raiz) sao processadas com stub parent
        reconstruido a partir de ~/.claude/usage-data/session-meta/<uuid>.json.
        """
        orphan_count = 0
        for project_dir in sorted(input_path.iterdir()):
            if not project_dir.is_dir():
                continue

            # 1) JSONLs raiz + subagents dessas sessoes
            processed_parents: set[str] = set()
            for session_file in sorted(project_dir.glob("*.jsonl")):
                parent_id = session_file.stem
                processed_parents.add(parent_id)
                self._parse_session(session_file, interaction_type="human_ai")

                subagents_dir = project_dir / parent_id / "subagents"
                if subagents_dir.is_dir():
                    for sub_file in sorted(subagents_dir.glob("*.jsonl")):
                        self._parse_session(
                            sub_file,
                            interaction_type="ai_ai",
                            parent_session_id=parent_id,
                        )

            # 2) Pastas <uuid>/subagents/ ORFAS (parent JSONL ausente)
            for item in sorted(project_dir.iterdir()):
                if not item.is_dir():
                    continue
                parent_id = item.name
                if parent_id in processed_parents:
                    continue
                subagents_dir = item / "subagents"
                if not subagents_dir.is_dir():
                    continue
                self._reconstruct_orphan_parent(parent_id, project_dir.name)
                for sub_file in sorted(subagents_dir.glob("*.jsonl")):
                    self._parse_session(
                        sub_file,
                        interaction_type="ai_ai",
                        parent_session_id=parent_id,
                    )
                orphan_count += 1

        if orphan_count:
            logger.info(f"  Claude Code: {orphan_count} sessoes orfas (stub parent reconstruido)")

    def parse_files(self, files: list[Path]) -> None:
        """Processa lista especifica de arquivos (uso incremental).

        Detecta root vs subagent pelo path:
        - Root:     <project>/<uuid>.jsonl → interaction_type=human_ai
        - Subagent: <project>/<parent_uuid>/subagents/<sub_uuid>.jsonl → ai_ai, parent=uuid
        """
        for session_file in files:
            parts = session_file.parts
            if "subagents" in parts:
                # .../<project>/<parent_uuid>/subagents/<sub_uuid>.jsonl
                parent_id = session_file.parent.parent.name
                self._parse_session(
                    session_file,
                    interaction_type="ai_ai",
                    parent_session_id=parent_id,
                )
            else:
                self._parse_session(session_file, interaction_type="human_ai")

    def _reconstruct_orphan_parent(self, parent_id: str, project_name: str) -> None:
        """Cria stub parent para sessao orfa a partir do session-meta.

        JSONL raiz sumiu (bug do CC pre-mar/2026) mas subagents + session-meta
        sobreviveram. Reconstroi conversation com first_prompt + stats reais.
        """
        meta_path = _SESSION_META_DIR / f"{parent_id}.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"  {parent_id}: falha ao ler session-meta: {e}")

        first_prompt = meta.get("first_prompt") or ""
        start_time = meta.get("start_time")
        user_count = meta.get("user_message_count", 0)
        assistant_count = meta.get("assistant_message_count", 0)
        project_path = meta.get("project_path")
        user_ts = meta.get("user_message_timestamps") or []

        created_at = self._ts(start_time) if start_time else pd.NaT
        updated_at = self._ts(user_ts[-1]) if user_ts else created_at

        messages = []
        if first_prompt:
            messages.append(Message(
                message_id=f"{parent_id}_stub_1",
                conversation_id=parent_id,
                source=self.source_name,
                sequence=1,
                role="user",
                content=first_prompt,
                model=None,
                created_at=created_at,
                account=self.account,
                content_types="text",
            ))

        # message_count preserva a contagem real (mesmo com mensagens perdidas)
        # Documenta lacuna via title: sessao real tinha N msgs, aqui so o first_prompt
        total_msgs = user_count + assistant_count
        title = f"[orphan parent — {total_msgs} msgs originais, JSONL perdido]"

        self.conversations.append(Conversation(
            conversation_id=parent_id,
            source=self.source_name,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            message_count=total_msgs,
            model=None,
            account=self.account,
            mode="cli",
            project=project_path,
            interaction_type="human_ai",
        ))
        if messages:
            self.messages.extend(messages)

    def _parse_session(
        self,
        session_file: Path,
        interaction_type: str = "human_ai",
        parent_session_id: str | None = None,
    ) -> None:
        lines = session_file.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(line) for line in lines if line.strip()]

        # Subagents (ai_ai): processar todos os eventos (isSidechain=true e o esperado)
        # Sessoes principais (human_ai): filtrar sidechain
        if interaction_type == "human_ai":
            main_events = [e for e in events if not e.get("isSidechain", False)]
        else:
            main_events = events

        # Subagents usam filename como conversation_id (sessionId nos eventos e o do pai)
        if interaction_type == "ai_ai":
            session_id = session_file.stem  # ex: agent-abc123
        else:
            session_id = None
        cwd = None
        slug = None
        messages = []
        tool_events = []
        tool_results = {}  # tool_use_id → result info
        seq = 0

        # Primeiro passo: coletar tool_results dos user messages
        for evt in main_events:
            if evt.get("type") == "user":
                content = evt.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            tool_use_id = item.get("tool_use_id")
                            if tool_use_id:
                                tool_results[tool_use_id] = {
                                    "is_error": item.get("is_error", False),
                                    "content": item.get("content", ""),
                                }

        # Segundo passo: processar eventos
        for evt in main_events:
            etype = evt.get("type")
            if not session_id:
                session_id = evt.get("sessionId") if interaction_type == "human_ai" else session_file.stem
            if not cwd:
                cwd = evt.get("cwd")
            if not slug:
                slug = evt.get("slug")

            if etype == "user":
                # Verificar se e user real (text) ou tool_result (continuacao)
                content = evt.get("message", {}).get("content", [])

                # content pode ser string direta ou lista de blocos
                if isinstance(content, str):
                    text_parts = [content] if content.strip() else []
                elif isinstance(content, list):
                    text_parts = [item.get("text", "") for item in content
                                  if isinstance(item, dict) and item.get("type") == "text"]
                else:
                    continue

                if not text_parts:
                    continue  # So tem tool_result, nao gera Message

                seq += 1
                messages.append(Message(
                    message_id=evt.get("uuid", f"{session_id}_{seq}"),
                    conversation_id=session_id,
                    source=self.source_name,
                    sequence=seq,
                    role="user",
                    content="\n\n".join(text_parts),
                    model=None,
                    created_at=self._ts(evt.get("timestamp")),
                    account=self.account,
                    content_types="text",
                ))

            elif etype == "assistant":
                msg_data = evt.get("message", {})
                content_blocks = msg_data.get("content", [])

                text_parts = []
                thinking_parts = []
                ct_types = set()

                for block in content_blocks:
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                        ct_types.add("text")
                    elif btype == "thinking":
                        thinking_parts.append(block.get("thinking", ""))
                        ct_types.add("thinking")
                    elif btype == "tool_use":
                        ct_types.add("tool_use")
                        tool_idx = len(tool_events)
                        tool_id = block.get("id")
                        tool_input = block.get("input", {})
                        result_info = tool_results.get(tool_id, {})

                        tool_events.append(ToolEvent(
                            event_id=tool_id or f"{session_id}_tool_{tool_idx}",
                            conversation_id=session_id,
                            message_id=evt.get("uuid", ""),
                            source=self.source_name,
                            event_type="tool_call",
                            tool_name=block.get("name", ""),
                            file_path=tool_input.get("file_path"),
                            command=tool_input.get("command"),
                            success=not result_info.get("is_error", False) if result_info else None,
                        ))

                seq += 1
                usage = msg_data.get("usage", {})
                token_count = (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) or None

                messages.append(Message(
                    message_id=evt.get("uuid", f"{session_id}_{seq}"),
                    conversation_id=session_id,
                    source=self.source_name,
                    sequence=seq,
                    role="assistant",
                    content="\n\n".join(text_parts) if text_parts else "",
                    model=msg_data.get("model"),
                    created_at=self._ts(evt.get("timestamp")),
                    account=self.account,
                    token_count=token_count,
                    thinking="\n\n".join(thinking_parts) if thinking_parts else None,
                    content_types=",".join(sorted(ct_types)) if ct_types else "text",
                ))

        if not session_id or not messages:
            return

        timestamps = [m.created_at for m in messages if m.created_at is not None]

        self.conversations.append(Conversation(
            conversation_id=session_id,
            source=self.source_name,
            title=slug,
            created_at=min(timestamps) if timestamps else None,
            updated_at=max(timestamps) if timestamps else None,
            message_count=len(messages),
            model=None,  # varia por msg
            account=self.account,
            mode="cli",
            project=cwd,
            interaction_type=interaction_type,
            parent_session_id=parent_session_id,
        ))
        self.messages.extend(messages)
        self.events.extend(tool_events)
