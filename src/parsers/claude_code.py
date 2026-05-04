"""Parser canonico v3 do Claude Code CLI.

Le sessoes JSONL de `data/raw/Claude Code/<encoded-cwd>/*.jsonl` (e subagents
em `<encoded-cwd>/<session-id>/subagents/*.jsonl`).

Gotchas mapeados (do projeto pai — 14 tests, multiples bug fixes):

1. **`content` pode ser str OU list** — fix recuperou 10.7k msgs (commit a391e5d).
2. **Sessoes orfas** — JSONL raiz some mas subagents + ~/.claude/usage-data/
   session-meta/<uuid>.json sobrevivem. Reconstroi stub parent (commit d2b2ffc:
   resgatou 352 sessoes + 1723 subagents).
3. **`isSidechain` filter** — sessoes principais filtram sidechain=True;
   subagents processam tudo.
4. **Subagent `conversation_id` usa filename** (nao sessionId — colidia com parent,
   commit 66d5cbc).
5. **`tool_results` em user msgs seguintes** — 2 passes pra correlacionar.
6. **`interaction_type`** — 'human_ai' (raiz) vs 'ai_ai' (subagent) +
   `parent_session_id` no subagent.

Output: data/processed/Claude Code/{claude_code_conversations,messages,
tool_events,branches}.parquet (4 parquets canonicos v3).

Branches: 1 _main por Conversation (Claude Code nao tem fork — chat eh linear).
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


# Metadados de sessao ficam em ~/.claude/usage-data/session-meta/<uuid>.json
# Mesmo quando o JSONL raiz some, o meta geralmente sobrevive (first_prompt, stats)
_SESSION_META_DIR = Path.home() / ".claude" / "usage-data" / "session-meta"


class ClaudeCodeParser(BaseParser):
    source_name = "claude_code"

    def __init__(self, account: Optional[str] = None):
        super().__init__(account=account)
        self.branches: list[Branch] = []
        self._chain_links: dict[str, str] = {}
        self._conv_source_files: dict[str, set[str]] = {}
        self._input_path: Optional[Path] = None

    def reset(self):
        super().reset()
        self.branches = []
        self._chain_links = {}
        self._conv_source_files = {}
        self._input_path = None

    def parse(self, input_path: Path) -> None:
        """Le sessoes JSONL de todos os projetos em input_path.

        input_path deve conter subdiretorios por projeto (formato encoded-cwd:
        `-Users-xxx-Desktop-project/`). Cada diretorio contem:
          - *.jsonl (sessoes principais)
          - {session-uuid}/subagents/*.jsonl (subagents)

        **Threads compactadas (`/compact`)**: o Claude Code grava JSONLs novos
        com filename diferente do `sessionId` interno quando o usuario faz
        `/compact`. Cada arquivo tem 1 evento inicial referenciando o parent
        sessionId — e os demais eventos com sessionId=filename. Reconstroi a
        thread logica seguindo essa cadeia: TODOS os JSONLs com mesmo
        sessionId raiz consolidam numa unica Conversation (conv_id = raiz).

        Sessoes orfas (root sem JSONL proprio mas com subagents/ + session-meta)
        ainda sao processadas com stub parent — porem so quando a propria raiz
        nao tem nenhum JSONL apontando pra ela.
        """
        input_path = Path(input_path)
        self._input_path = input_path

        # FASE 1: descobrir cadeias de compactacao globalmente
        self._chain_links = self._build_chain_links(input_path)

        orphan_count = 0
        for project_dir in sorted(input_path.iterdir()):
            if not project_dir.is_dir():
                continue

            # 1) JSONLs raiz + subagents dessas sessoes
            processed_filenames: set[str] = set()
            for session_file in sorted(project_dir.glob("*.jsonl")):
                filename_id = session_file.stem
                processed_filenames.add(filename_id)
                root_id = self._find_root(filename_id)

                # override_conv_id=root_id consolida todos JSONLs da thread
                # numa unica Conversation
                self._parse_session(
                    session_file,
                    interaction_type="human_ai",
                    override_conv_id=root_id,
                )

                subagents_dir = project_dir / filename_id / "subagents"
                if subagents_dir.is_dir():
                    for sub_file in sorted(subagents_dir.glob("*.jsonl")):
                        # parent_session_id sempre aponta pra raiz da thread,
                        # nao pro filename intermediario
                        self._parse_session(
                            sub_file,
                            interaction_type="ai_ai",
                            parent_session_id=root_id,
                        )

            # 2) Pastas <uuid>/subagents/ sem JSONL proprio
            for item in sorted(project_dir.iterdir()):
                if not item.is_dir():
                    continue
                folder_id = item.name
                if folder_id in processed_filenames:
                    continue
                subagents_dir = item / "subagents"
                if not subagents_dir.is_dir():
                    continue

                root_id = self._find_root(folder_id)
                # Se folder_id eh a raiz da thread (e nao mid-cadeia), criar stub
                if root_id == folder_id:
                    self._reconstruct_orphan_parent(folder_id, project_dir.name)
                    orphan_count += 1

                # Subagents sempre apontam pra raiz (mesmo se folder eh mid-cadeia)
                for sub_file in sorted(subagents_dir.glob("*.jsonl")):
                    self._parse_session(
                        sub_file,
                        interaction_type="ai_ai",
                        parent_session_id=root_id,
                    )

        if orphan_count:
            logger.info(f"  Claude Code: {orphan_count} sessoes orfas (stub parent reconstruido)")

        self._build_branches()
        from src.extractors.cli.preservation import mark_cli_preservation
        mark_cli_preservation(self)

    def _build_chain_links(self, input_path: Path) -> dict[str, str]:
        """Identifica cadeias de compactacao varrendo o primeiro sessionId de
        cada JSONL.

        Quando o usuario faz `/compact`, o JSONL novo tem o sessionId interno
        do parent no PRIMEIRO evento (e dominante=filename nos demais). Aqui
        coletamos esse "ponteiro" pra construir o grafo de cadeias.

        Retorna: {filename → parent_sessionId} pra arquivos com cadeia
        detectada (filename != primeiro_sessionId).
        """
        links: dict[str, str] = {}
        for project_dir in input_path.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl in project_dir.glob("*.jsonl"):
                filename_id = jsonl.stem
                first_sid = None
                try:
                    with open(jsonl, encoding="utf-8") as f:
                        for line in f:
                            try:
                                evt = json.loads(line)
                                sid = evt.get("sessionId")
                                if sid:
                                    first_sid = sid
                                    break
                            except json.JSONDecodeError:
                                continue
                except OSError:
                    continue
                if first_sid and first_sid != filename_id:
                    links[filename_id] = first_sid
        return links

    def _find_root(self, filename_id: str) -> str:
        """Segue chain_links ate a raiz da thread (sem parent)."""
        seen = set()
        current = filename_id
        while current in self._chain_links and current not in seen:
            seen.add(current)
            current = self._chain_links[current]
        return current

    def parse_files(self, files: list[Path]) -> None:
        """Processa lista especifica de arquivos (uso incremental).

        Detecta root vs subagent pelo path:
        - Root:     <project>/<uuid>.jsonl → interaction_type=human_ai
        - Subagent: <project>/<parent_uuid>/subagents/<sub_uuid>.jsonl → ai_ai, parent=uuid
        """
        for session_file in files:
            parts = session_file.parts
            if "subagents" in parts:
                parent_id = session_file.parent.parent.name
                self._parse_session(
                    session_file,
                    interaction_type="ai_ai",
                    parent_session_id=parent_id,
                )
            else:
                self._parse_session(session_file, interaction_type="human_ai")
        self._build_branches()

    def _build_branches(self) -> None:
        """Gera 1 Branch <conv>_main por Conversation. Claude Code nao tem fork."""
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
            if conv_msgs:
                root_id = conv_msgs[0].message_id
                leaf_id = conv_msgs[-1].message_id
            else:
                root_id = ""
                leaf_id = ""
            self.branches.append(Branch(
                branch_id=f"{conv.conversation_id}_main",
                conversation_id=conv.conversation_id,
                source=self.source_name,
                root_message_id=root_id,
                leaf_message_id=leaf_id,
                is_active=True,
                created_at=conv.created_at if conv.created_at is not None else pd.Timestamp.now(tz="UTC"),
            ))

    def _reconstruct_orphan_parent(self, parent_id: str, project_name: str) -> None:
        """Cria stub parent para sessao orfa a partir do session-meta.

        JSONL raiz sumiu (bug do CC pre-mar/2026) mas subagents + session-meta
        sobreviveram. Reconstroi conversation com first_prompt + stats reais.

        Idempotente: se conv `parent_id` ja existe (criada via cadeia
        compactada que aponta pra esse parent), nao cria dup — apenas anexa
        o stub message se nao houver primeira msg ainda.
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

        existing = next(
            (c for c in self.conversations if c.conversation_id == parent_id),
            None,
        )
        if existing:
            # Conv ja existe (mensagens vieram via cadeia compactada). NAO duplica;
            # apenas atualiza campos vazios e mantem timestamps mais antigos.
            if not existing.project and project_path:
                existing.project = project_path
            if pd.notna(created_at) and (existing.created_at is None or created_at < existing.created_at):
                existing.created_at = created_at
            return

        # Conv nao existe: cria stub completo
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
        parent_session_id: Optional[str] = None,
        override_conv_id: Optional[str] = None,
    ) -> None:
        try:
            text = session_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"  {session_file}: falha ao ler: {e}")
            return
        lines = text.strip().split("\n")
        events = []
        seen_uuids: set[str] = set()  # dedup eventos repetidos no JSONL bruto
        for line in lines:
            if not line.strip():
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip malformed lines
            # Bug do Claude Code: subagents JSONL pode gravar o MESMO evento
            # ate 3x (mesmo uuid, timestamp, content). Dedup defensivo aqui.
            uuid = evt.get("uuid")
            if uuid and uuid in seen_uuids:
                continue
            if uuid:
                seen_uuids.add(uuid)
            events.append(evt)

        # Subagents (ai_ai): processar todos os eventos (isSidechain=true e o esperado)
        # Sessoes principais (human_ai): filtrar sidechain
        if interaction_type == "human_ai":
            main_events = [e for e in events if not e.get("isSidechain", False)]
        else:
            main_events = events

        # Subagents usam filename como conversation_id (sessionId nos eventos e o do pai)
        if interaction_type == "ai_ai":
            session_id: Optional[str] = session_file.stem  # ex: agent-abc123
        else:
            session_id = None
        cwd = None
        slug = None
        messages: list[Message] = []
        tool_events: list[ToolEvent] = []
        tool_results: dict[str, dict] = {}  # tool_use_id → result info
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
                content = evt.get("message", {}).get("content", [])

                # GOTCHA: content pode ser string direta ou lista de blocos
                # Bug pre-a391e5d descartava string content, perdendo 10.7k msgs
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

                text_parts: list[str] = []
                thinking_parts: list[str] = []
                ct_types: set[str] = set()

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
                        tool_input = block.get("input", {}) or {}
                        result_info = tool_results.get(tool_id, {}) if tool_id else {}

                        tool_events.append(ToolEvent(
                            event_id=tool_id or f"{session_id}_tool_{tool_idx}",
                            conversation_id=session_id,
                            message_id=evt.get("uuid", ""),
                            source=self.source_name,
                            event_type="tool_call",
                            tool_name=block.get("name", ""),
                            file_path=tool_input.get("file_path"),
                            command=tool_input.get("command"),
                            success=(not result_info.get("is_error", False))
                            if result_info else None,
                        ))

                seq += 1
                usage = msg_data.get("usage", {}) or {}
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

        # Override conv_id (usado quando este JSONL pertence a uma thread
        # compactada — todos os JSONLs da thread consolidam em conv_id=raiz).
        if override_conv_id:
            final_conv_id = override_conv_id
            for m in messages:
                m.conversation_id = final_conv_id
            for e in tool_events:
                e.conversation_id = final_conv_id
        else:
            final_conv_id = session_id

        # Registra rel path do session_file pra preservation tracking.
        # Pra threads compactadas: todos os JSONLs (root + subagents) contam
        # pro final_conv_id. Pra subagents: tambem registra pro parent
        # (preservation eh thread-level: thread sumiu = parent + subagents
        # todos sumiram).
        if self._input_path is not None:
            try:
                rel = str(session_file.relative_to(self._input_path))
                self._conv_source_files.setdefault(final_conv_id, set()).add(rel)
                if parent_session_id:
                    self._conv_source_files.setdefault(parent_session_id, set()).add(rel)
            except ValueError:
                pass

        timestamps = [m.created_at for m in messages if m.created_at is not None]
        new_min = min(timestamps) if timestamps else None
        new_max = max(timestamps) if timestamps else None

        # MERGE em conv existente quando override aponta pra conv ja criada
        # (caso de N JSONLs da mesma thread compactada).
        existing = next((c for c in self.conversations if c.conversation_id == final_conv_id), None)
        if existing:
            # Acumula contagem; expande janela de timestamps; mantem cwd/slug
            # ja registrados. Renumera sequence pra evitar colisao.
            offset = existing.message_count
            for m in messages:
                m.sequence += offset
            existing.message_count += len(messages)
            if new_min and (existing.created_at is None or new_min < existing.created_at):
                existing.created_at = new_min
            if new_max and (existing.updated_at is None or new_max > existing.updated_at):
                existing.updated_at = new_max
            # Title (slug): preserva o ja existente; preenche com slug atual se vazio
            if not existing.title and slug:
                existing.title = slug
            if not existing.project and cwd:
                existing.project = cwd
        else:
            self.conversations.append(Conversation(
                conversation_id=final_conv_id,
                source=self.source_name,
                title=slug,
                created_at=new_min,
                updated_at=new_max,
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

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def write_parquets(self, output_dir: Path) -> dict[str, int]:
        """Escreve 4 parquets canonicos em output_dir. Idempotente."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        conversations_to_df(self.conversations).to_parquet(
            output_dir / "claude_code_conversations.parquet", index=False)
        messages_to_df(self.messages).to_parquet(
            output_dir / "claude_code_messages.parquet", index=False)
        tool_events_to_df(self.events).to_parquet(
            output_dir / "claude_code_tool_events.parquet", index=False)
        branches_to_df(self.branches).to_parquet(
            output_dir / "claude_code_branches.parquet", index=False)
        return {
            "conversations": len(self.conversations),
            "messages": len(self.messages),
            "tool_events": len(self.events),
            "branches": len(self.branches),
        }
