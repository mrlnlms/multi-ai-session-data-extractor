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
        self._conv_source_files: dict[str, set[str]] = {}
        self._input_path: Optional[Path] = None

    def reset(self):
        super().reset()
        self.branches = []
        self._conv_source_files = {}
        self._input_path = None

    def parse(self, input_path: Path) -> None:
        """Le sessoes JSON de todos os projetos em input_path.

        input_path = raiz (ex: data/raw/Gemini CLI/) com subdirs por projeto,
        cada um com chats/*.json e opcionalmente logs.json.
        """
        input_path = Path(input_path)
        self._input_path = input_path
        for project_dir in sorted(input_path.iterdir()):
            if not project_dir.is_dir():
                continue
            # Note: chats_dir pode nao existir se o workspace so tem logs.json (orphan-only)
            project_name = self._resolve_project_name(project_dir)
            chats_dir = project_dir / "chats"
            if chats_dir.exists():
                for session_file in sorted(chats_dir.glob("session-*.json")):
                    self._parse_session(session_file, project_name)
            # logs.json orphan handling — corre depois de chats/ pra saber quais sids ja existem
            self._ingest_orphans_from_logs(project_dir, project_name)
        self._build_branches()
        from src.extractors.cli.preservation import mark_cli_preservation
        mark_cli_preservation(self)

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

    def _ingest_orphans_from_logs(self, project_dir: Path, project_name: str) -> None:
        """Le logs.json e cria Conversations/Messages pra session_ids sem chats correspondente.

        Schema do logs.json (lista de):
          {sessionId, messageId, type, message, timestamp}

        Apenas type='user' eh ingerido (logs.json so tem prompts do user, sem
        respostas do agente). Sessions cujos session-*.json existem em chats/
        sao ignoradas — chats/ eh fonte canonica.
        """
        logs_file = project_dir / "logs.json"
        if not logs_file.exists():
            return
        try:
            logs = json.loads(logs_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"  {project_dir.name}: logs.json invalid — {e}")
            return
        if not isinstance(logs, list):
            return

        # Set de session_ids ja processados via chats/
        chats_dir = project_dir / "chats"
        existing_sids: set[str] = set()
        if chats_dir.exists():
            for sf in chats_dir.glob("session-*.json"):
                try:
                    existing_sids.add(json.loads(sf.read_text(encoding="utf-8")).get("sessionId"))
                except Exception:
                    pass

        # Group entries by sessionId, filter type=user, skip se session ja existe
        by_sid: dict[str, list[dict]] = {}
        for entry in logs:
            if not isinstance(entry, dict):
                continue
            sid = entry.get("sessionId")
            if not sid or sid in existing_sids:
                continue
            if entry.get("type") != "user":
                continue
            by_sid.setdefault(sid, []).append(entry)

        for sid, entries in by_sid.items():
            entries_sorted = sorted(entries, key=lambda e: e.get("messageId", 0))
            first_ts = entries_sorted[0].get("timestamp")
            last_ts = entries_sorted[-1].get("timestamp")
            created_at = self._ts(first_ts) if first_ts else pd.NaT
            updated_at = self._ts(last_ts) if last_ts else created_at

            self.conversations.append(Conversation(
                conversation_id=sid,
                source="gemini_cli",
                title=None,
                created_at=created_at,
                updated_at=updated_at,
                message_count=len(entries_sorted),
                model=None,
                project=project_name,
                is_preserved_missing=True,
            ))
            for entry in entries_sorted:
                ts = entry.get("timestamp")
                self.messages.append(Message(
                    message_id=f"{sid}_msg_{entry.get('messageId', 0)}",
                    conversation_id=sid,
                    source="gemini_cli",
                    sequence=int(entry.get("messageId", 0)),
                    role="user",
                    content=entry.get("message", "") or "",
                    model=None,
                    created_at=self._ts(ts) if ts else pd.NaT,
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

        # Registra rel path pra preservation tracking
        if self._input_path is not None:
            try:
                rel = str(session_file.relative_to(self._input_path))
                self._conv_source_files.setdefault(session_id, set()).add(rel)
            except ValueError:
                pass

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

        # Gemini CLI grava snapshots periodicos: varios arquivos
        # `session-<timestamp>-<sid>.json` com mesmo sessionId interno. As msgs
        # se sobrepoem entre snapshots (snapshot mais novo eh superset). Aqui
        # consolidamos numa unica Conversation por sessionId, deduplicando msgs
        # por id (preservation: mantemos a maior cobertura).
        existing = next(
            (c for c in self.conversations if c.conversation_id == session_id),
            None,
        )
        if existing:
            # Dedup: pegar apenas msgs com id que nao apareceu antes nessa conv
            existing_msg_ids = {
                m.message_id for m in self.messages
                if m.conversation_id == session_id
            }
            new_msgs = [m for m in messages if m.message_id not in existing_msg_ids]
            if new_msgs:
                # Renumera sequence pra continuar do ultimo
                offset = existing.message_count
                for m in new_msgs:
                    m.sequence += offset
                self.messages.extend(new_msgs)
                existing.message_count += len(new_msgs)
            # Mesma logica pros tool_events
            existing_evt_ids = {
                e.event_id for e in self.events
                if e.conversation_id == session_id
            }
            new_events = [e for e in events if e.event_id not in existing_evt_ids]
            if new_events:
                self.events.extend(new_events)
            # Expande janela de timestamps
            if created_at is not None and (existing.created_at is None or created_at < existing.created_at):
                existing.created_at = created_at
            if updated_at is not None and (existing.updated_at is None or updated_at > existing.updated_at):
                existing.updated_at = updated_at
        else:
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
