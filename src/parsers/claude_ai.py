"""Parser canonico do Claude.ai — schema v3.

Consome merged em data/merged/Claude.ai/conversations/<uuid>.json (1 file por
conv) + projects/<uuid>.json + assets/. Gera 4 parquets canonicos.

Cobertura:
- Branches via parent_message_uuid + current_leaf_message_uuid (DAG plano,
  diferente do tree-walk do ChatGPT — ver _claude_ai_helpers.build_branches)
- Thinking blocks → Message.thinking
- Tool use/result blocks → ToolEvent (incl. MCP via integration_name)
- Attachments com extracted_content → Message.attachment_names
- Files (uploads binarios) → Message.asset_paths via assets_root
- Pin (is_starred) → Conversation.is_pinned
- is_temporary preservado em Conversation.is_temporary
- Preservation: is_preserved_missing + last_seen_in_server
- Project metadata em Conversation.project_id + .project (nome)

Output: data/processed/Claude.ai/{conversations,messages,tool_events,branches}.parquet

Versao anterior (legacy MVP de 159 linhas) ficou em
_backup-temp/parser-claude-ai-promocao-2026-05-01/ pra rollback.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers._claude_ai_helpers import (
    block_time_bounds_iso,
    build_branches,
    classify_tool_event,
    collect_attachment_names,
    collect_block_types,
    collect_citations,
    concat_text_blocks,
    concat_thinking_blocks,
    is_mcp_tool_use,
    resolve_file_assets,
    serialize_attachments,
)
from src.parsers.base import BaseParser
from src.schema.models import (
    Branch,
    Conversation,
    Message,
    ProjectDoc,
    ToolEvent,
    branches_to_df,
    conversations_to_df,
    messages_to_df,
    project_docs_to_df,
    tool_events_to_df,
)


SOURCE = "claude_ai"

ROLE_MAP = {"human": "user", "assistant": "assistant"}


class ClaudeAIParser(BaseParser):
    source_name = SOURCE

    def __init__(
        self,
        account: Optional[str] = None,
        merged_root: Optional[Path] = None,
    ):
        super().__init__(account)
        self.merged_root = Path(merged_root) if merged_root else Path("data/merged/Claude.ai")
        self.projects: list[dict] = []  # raw project dicts (para tabela separada)

    def reset(self):
        super().reset()
        self.branches: list[Branch] = []
        self.projects = []
        self.project_docs: list[ProjectDoc] = []

    @property
    def conversations_dir(self) -> Path:
        return self.merged_root / "conversations"

    @property
    def projects_dir(self) -> Path:
        return self.merged_root / "projects"

    @property
    def assets_root(self) -> Path:
        return self.merged_root / "assets"

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def parse(self, input_path: Path) -> None:
        """Ingere uma pasta merged completa OU um unico arquivo de conv.

        Aceita:
        - Path pra pasta data/merged/Claude.ai/ → varre conversations/ e projects/
        - Path pra arquivo individual conversations/<uuid>.json → parsea um conv
        """
        input_path = Path(input_path)
        if input_path.is_dir():
            self._parse_merged_dir(input_path)
        elif input_path.is_file():
            with open(input_path, encoding="utf-8") as f:
                conv = json.load(f)
            self._parse_conv(conv, last_run_date=conv.get("_last_seen_in_server"))
        else:
            raise FileNotFoundError(f"Input nao existe: {input_path}")

    def _parse_merged_dir(self, merged_root: Path) -> None:
        """Varre conversations/ e projects/ na pasta merged."""
        self.merged_root = merged_root
        conv_dir = merged_root / "conversations"
        proj_dir = merged_root / "projects"

        # Calcula last_run_date global pra derivar is_preserved_missing de forma idempotente
        last_run_date = self._compute_last_run_date(conv_dir)

        # Conversations
        if conv_dir.exists():
            for fp in sorted(conv_dir.glob("*.json")):
                try:
                    with open(fp, encoding="utf-8") as f:
                        conv = json.load(f)
                except Exception as e:
                    # Skip arquivo corromp, mas registra warning silencioso
                    continue
                self._parse_conv(conv, last_run_date=last_run_date)

        # Projects (raw + project_docs como tabela separada com content)
        if proj_dir.exists():
            for fp in sorted(proj_dir.glob("*.json")):
                try:
                    with open(fp, encoding="utf-8") as f:
                        proj = json.load(f)
                except Exception:
                    continue
                self.projects.append(proj)
                self._extract_project_docs(proj)

    @staticmethod
    def _compute_last_run_date(conv_dir: Path) -> Optional[str]:
        """Maior _last_seen_in_server entre as convs do merged.

        Usado pra derivar is_preserved_missing idempotente: conv preservada
        eh aquela cuja last_seen_in_server eh menor que a maior data global
        (ou tem flag _preserved_missing setada explicita pelo reconciler).
        """
        if not conv_dir.exists():
            return None
        seens = []
        for fp in conv_dir.glob("*.json"):
            try:
                with open(fp, encoding="utf-8") as f:
                    obj = json.load(f)
                v = obj.get("_last_seen_in_server")
                if v:
                    seens.append(v)
            except Exception:
                continue
        return max(seens) if seens else None

    # ------------------------------------------------------------------
    # Per-conv parsing
    # ------------------------------------------------------------------

    def _parse_conv(self, conv: dict, last_run_date: Optional[str]) -> None:
        conv_uuid = conv.get("uuid")
        if not conv_uuid:
            return

        chat_messages = conv.get("chat_messages") or []
        current_leaf = conv.get("current_leaf_message_uuid")

        # Branches
        msg_to_branch, branch_records = build_branches(
            conv_uuid, chat_messages, current_leaf
        )

        # Build messages
        messages: list[Message] = []
        tool_events: list[ToolEvent] = []
        for seq, msg in enumerate(chat_messages, start=1):
            built = self._build_message(conv_uuid, conv, msg, seq, msg_to_branch)
            if built is None:
                continue
            messages.append(built)
            # Tool events derivados desta msg
            tool_events.extend(self._extract_tool_events(conv_uuid, msg))

        # Branch records → Branch dataclass
        for br in branch_records:
            self.branches.append(Branch(
                branch_id=br["branch_id"],
                conversation_id=conv_uuid,
                source=SOURCE,
                root_message_id=br["root_message_id"],
                leaf_message_id=br["leaf_message_id"],
                is_active=br["is_active"],
                created_at=self._ts(br["created_at"]),
                parent_branch_id=br["parent_branch_id"],
            ))

        # Conversation
        proj_dict = conv.get("project") or {}
        last_seen = conv.get("_last_seen_in_server")
        is_preserved = bool(conv.get("_preserved_missing")) or (
            last_run_date is not None
            and last_seen is not None
            and last_seen < last_run_date
        )

        # settings preservados como JSON pra futuras consultas (paprika_mode,
        # web_search, artifacts, etc — features flags por conv).
        settings = conv.get("settings")
        settings_json = (
            json.dumps(settings, ensure_ascii=False)
            if isinstance(settings, dict) and settings
            else None
        )
        summary = conv.get("summary") or None
        if summary == "":
            summary = None

        self.conversations.append(Conversation(
            conversation_id=conv_uuid,
            source=SOURCE,
            title=conv.get("name") or None,
            created_at=self._ts(conv.get("created_at")),
            updated_at=self._ts(conv.get("updated_at")),
            message_count=len(messages),
            model=conv.get("model"),
            account=self.account,
            mode="chat",
            project=(proj_dict.get("name") if isinstance(proj_dict, dict) else None),
            url=f"https://claude.ai/chat/{conv_uuid}",
            project_id=conv.get("project_uuid") or (
                proj_dict.get("uuid") if isinstance(proj_dict, dict) else None
            ),
            is_pinned=bool(conv.get("is_starred", False)),
            is_archived=None,  # Claude.ai nao expoe is_archived — None = feature nao existe upstream
            is_temporary=bool(conv.get("is_temporary", False)),
            is_preserved_missing=is_preserved,
            last_seen_in_server=self._ts(last_seen) if last_seen else None,
            summary=summary,
            settings_json=settings_json,
        ))

        self.messages.extend(messages)
        self.events.extend(tool_events)

    def _build_message(
        self,
        conv_uuid: str,
        conv: dict,
        msg: dict,
        seq: int,
        msg_to_branch: dict[str, str],
    ) -> Optional[Message]:
        sender = msg.get("sender", "")
        role = ROLE_MAP.get(sender)
        if role is None:
            return None

        msg_uuid = msg.get("uuid") or ""
        content_blocks = msg.get("content") or []

        text_content = concat_text_blocks(content_blocks)
        thinking = concat_thinking_blocks(content_blocks)
        block_types = collect_block_types(content_blocks)

        # Attachments com extracted_content (1.8k+ no projeto-mae,
        # texto extraido fica inline em attachments_json)
        attachments = msg.get("attachments") or []
        att_names = collect_attachment_names(attachments)
        att_serialized = serialize_attachments(attachments)
        attachments_json = (
            json.dumps(att_serialized, ensure_ascii=False) if att_serialized else None
        )

        # Files (binarios) → asset_paths
        files = msg.get("files") or []
        asset_paths = resolve_file_assets(files, self.assets_root)

        # Adicionar attachments aos content_types pra rastreabilidade
        if attachments and "attachment" not in block_types:
            block_types.append("attachment")
        if files and "file" not in block_types:
            block_types.append("file")

        # Citations agregadas (de blocks `text`)
        citations = collect_citations(content_blocks)
        citations_json = (
            json.dumps(citations, ensure_ascii=False) if citations else None
        )

        # Timestamps de bloco (latencia: max(stop) - min(start))
        start_ts_str, stop_ts_str = block_time_bounds_iso(content_blocks)

        model = conv.get("model") if role == "assistant" else None
        branch_id = msg_to_branch.get(msg_uuid, f"{conv_uuid}_main")

        return Message(
            message_id=msg_uuid,
            conversation_id=conv_uuid,
            source=SOURCE,
            sequence=seq,
            role=role,
            content=text_content,
            model=model,
            created_at=self._ts(msg.get("created_at")),
            account=self.account,
            attachment_names=json.dumps(att_names, ensure_ascii=False) if att_names else None,
            content_types=",".join(block_types) if block_types else "text",
            thinking=thinking,
            branch_id=branch_id,
            asset_paths=asset_paths,
            finish_reason=msg.get("stop_reason"),
            citations_json=citations_json,
            attachments_json=attachments_json,
            start_timestamp=self._ts(start_ts_str) if start_ts_str else None,
            stop_timestamp=self._ts(stop_ts_str) if stop_ts_str else None,
        )

    def _extract_tool_events(self, conv_uuid: str, msg: dict) -> list[ToolEvent]:
        """Extrai 1 ToolEvent por block tool_use/tool_result.

        event_type formato: '<categoria>_call' ou '<categoria>_result'.
        Categoria via classify_tool_event; MCP detectado via integration_name.
        """
        events: list[ToolEvent] = []
        msg_uuid = msg.get("uuid") or ""
        content_blocks = msg.get("content") or []

        for idx, block in enumerate(content_blocks):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "tool_use":
                tool_name = block.get("name") or ""
                is_mcp = is_mcp_tool_use(block)
                category = classify_tool_event(tool_name, is_mcp)

                metadata = {
                    "tool_use_id": block.get("id"),
                    "input": block.get("input"),
                    "message": block.get("message"),
                    "icon_name": block.get("icon_name"),
                    "is_mcp": is_mcp,
                    "integration_name": block.get("integration_name"),
                    "integration_icon_url": block.get("integration_icon_url"),
                    "mcp_server_url": block.get("mcp_server_url"),
                    "is_mcp_app": block.get("is_mcp_app"),
                    "start_timestamp": block.get("start_timestamp"),
                    "stop_timestamp": block.get("stop_timestamp"),
                }
                events.append(ToolEvent(
                    event_id=f"{block.get('id') or msg_uuid + '_call_' + str(idx)}",
                    conversation_id=conv_uuid,
                    message_id=msg_uuid,
                    source=SOURCE,
                    event_type=f"{category}_call",
                    tool_name=tool_name or None,
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                ))

            elif btype == "tool_result":
                tool_use_id = block.get("tool_use_id") or ""
                tool_name = block.get("name") or ""
                is_error = bool(block.get("is_error"))
                # Result content pode ser list ou string — serializa
                result_content = block.get("content")

                # Sem 'is_mcp' confiavel aqui (tool_result nao traz integration_name);
                # usamos heuristica: se nome do tool nao bate com builtin, assume MCP
                from src.parsers._claude_ai_helpers import BUILTIN_TOOL_TYPE
                is_mcp_likely = tool_name not in BUILTIN_TOOL_TYPE
                category = classify_tool_event(tool_name, is_mcp_likely)

                metadata = {
                    "tool_use_id": tool_use_id,
                    "icon_name": block.get("icon_name"),
                    "is_error": is_error,
                }
                events.append(ToolEvent(
                    event_id=f"{tool_use_id}_result" if tool_use_id else f"{msg_uuid}_result_{idx}",
                    conversation_id=conv_uuid,
                    message_id=msg_uuid,
                    source=SOURCE,
                    event_type=f"{category}_result",
                    tool_name=tool_name or None,
                    success=not is_error,
                    result=(
                        json.dumps(result_content, ensure_ascii=False)
                        if not isinstance(result_content, str)
                        else result_content
                    ),
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                ))

        return events

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _extract_project_docs(self, proj: dict) -> None:
        """Coleta docs do project como ProjectDoc (com content inline)."""
        proj_uuid = proj.get("uuid")
        if not proj_uuid:
            return
        for doc in proj.get("docs") or []:
            if not isinstance(doc, dict):
                continue
            doc_uuid = doc.get("uuid")
            if not doc_uuid:
                continue
            content = doc.get("content") or ""
            etok = doc.get("estimated_token_count")
            try:
                etok_int = int(etok) if etok is not None else None
            except (TypeError, ValueError):
                etok_int = None
            self.project_docs.append(ProjectDoc(
                doc_id=doc_uuid,
                project_id=proj_uuid,
                source=SOURCE,
                file_name=doc.get("file_name") or "",
                content=content,
                content_size=len(content),
                estimated_token_count=etok_int,
                created_at=self._ts(doc.get("created_at")) if doc.get("created_at") else None,
            ))

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def project_docs_df(self) -> pd.DataFrame:
        return project_docs_to_df(self.project_docs)

    def project_metadata_df(self) -> pd.DataFrame:
        """Tabela auxiliar: 1 row por project, com docs_count + files_count
        e prompt_template. Project docs (content inline) NAO entram aqui —
        ficam no raw merged/projects/<uuid>.json."""
        if not self.projects:
            return pd.DataFrame(columns=[
                "project_id", "name", "description", "prompt_template",
                "created_at", "updated_at", "archived_at",
                "is_private", "is_starred", "is_starter_project",
                "docs_count", "files_count",
            ])
        rows = []
        for p in self.projects:
            rows.append({
                "project_id": p.get("uuid"),
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "prompt_template": p.get("prompt_template", ""),
                "created_at": self._ts(p.get("created_at")),
                "updated_at": self._ts(p.get("updated_at")),
                "archived_at": self._ts(p.get("archived_at")) if p.get("archived_at") else pd.NaT,
                "is_private": bool(p.get("is_private", True)),
                "is_starred": bool(p.get("is_starred", False)),
                "is_starter_project": bool(p.get("is_starter_project", False)),
                "docs_count": int(p.get("docs_count") or 0),
                "files_count": int(p.get("files_count") or 0),
            })
        return pd.DataFrame(rows)

    def save(self, output_dir: Path) -> None:
        """Salva 4 parquets canonicos + project_metadata auxiliar."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        conv_df = self.conversations_df()
        if not conv_df.empty:
            conv_df.to_parquet(output_dir / f"{self.source_name}_conversations.parquet")

        msg_df = self.messages_df()
        if not msg_df.empty:
            msg_df["word_count"] = msg_df["content"].fillna("").str.split().str.len()
            msg_df.to_parquet(output_dir / f"{self.source_name}_messages.parquet")

        evt_df = self.events_df()
        if not evt_df.empty:
            evt_df.to_parquet(output_dir / f"{self.source_name}_tool_events.parquet")

        br_df = self.branches_df()
        if not br_df.empty:
            br_df.to_parquet(output_dir / f"{self.source_name}_branches.parquet")

        proj_df = self.project_metadata_df()
        if not proj_df.empty:
            proj_df.to_parquet(output_dir / f"{self.source_name}_project_metadata.parquet")

        docs_df = self.project_docs_df()
        if not docs_df.empty:
            docs_df.to_parquet(output_dir / f"{self.source_name}_project_docs.parquet")
