"""Parser canonico do Qwen — schema v3.

Consome merged em data/merged/Qwen/conversations/<uuid>.json (1 file por
conv) + projects.json + assets/. Gera 4 parquets canonicos + project_metadata
+ project_docs auxiliar.

Cobertura (probe 2026-05-01):
- Branches via parentId + childrenIds + currentId (DAG plano, igual Claude.ai)
- reasoning_content → Message.thinking
- chat_type → Conversation.mode (com mapping pra VALID_MODES)
- search_results → ToolEvent (event_type=search_call/_result)
- pinned (✅ cross-platform) → Conversation.is_pinned
- archived → Conversation.is_archived
- meta.tags + feature_config → Conversation.settings_json
- content_list[*].timestamp → Message.start_timestamp/stop_timestamp
- files → Message.attachment_names
- Project com custom_instruction + _files → project_metadata + project_docs

Output: data/processed/Qwen/{conversations,messages,tool_events,branches,
project_metadata,project_docs}.parquet
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers._qwen_helpers import (
    CHAT_TYPE_TO_MODE,
    CHAT_TYPE_TO_TOOL_CATEGORY,
    block_time_bounds,
    build_branches_qwen,
    collect_file_names,
    collect_text_from_content_list,
    extract_search_results,
    serialize_settings,
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


SOURCE = "qwen"
ROLE_MAP = {"user": "user", "assistant": "assistant"}


def _normalize_epoch(v):
    """Qwen retorna epoch como string ('1777088048') OU int. Normaliza pra int.

    Retorna None se vazio/invalido. Tolera tambem float epoch.
    """
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v  # fallback ISO string — _ts() lida
    return v


class QwenParser(BaseParser):
    source_name = SOURCE

    def __init__(
        self,
        account: Optional[str] = None,
        merged_root: Optional[Path] = None,
    ):
        super().__init__(account)
        self.merged_root = Path(merged_root) if merged_root else Path("data/merged/Qwen")
        self.projects: list[dict] = []
        self.project_docs: list[ProjectDoc] = []

    def reset(self):
        super().reset()
        self.branches: list[Branch] = []
        self.projects = []
        self.project_docs = []

    @property
    def conversations_dir(self) -> Path:
        return self.merged_root / "conversations"

    def parse(self, input_path: Path) -> None:
        input_path = Path(input_path)
        if input_path.is_dir():
            self._parse_merged_dir(input_path)
        elif input_path.is_file():
            with open(input_path, encoding="utf-8") as f:
                envelope = json.load(f)
            data = envelope.get("data", envelope)
            self._parse_conv(data, last_run_date=envelope.get("_last_seen_in_server"))
        else:
            raise FileNotFoundError(f"Input nao existe: {input_path}")

    def _parse_merged_dir(self, merged_root: Path) -> None:
        self.merged_root = merged_root
        conv_dir = merged_root / "conversations"
        last_run_date = self._compute_last_run_date(conv_dir)

        # Conversations
        if conv_dir.exists():
            for fp in sorted(conv_dir.glob("*.json")):
                try:
                    with open(fp, encoding="utf-8") as f:
                        envelope = json.load(f)
                except Exception:
                    continue
                # Qwen raw envelope: {success, request_id, data: {...}, _last_seen_in_server: ...}
                data = envelope.get("data") or {}
                # Preservation flags vivem no envelope, nao no data
                if envelope.get("_preserved_missing"):
                    data["_preserved_missing"] = True
                if envelope.get("_last_seen_in_server"):
                    data["_last_seen_in_server"] = envelope["_last_seen_in_server"]
                self._parse_conv(data, last_run_date=last_run_date)

        # Projects (lista de dicts em projects.json)
        projects_path = merged_root / "projects.json"
        if projects_path.exists():
            try:
                projects = json.loads(projects_path.read_text(encoding="utf-8"))
            except Exception:
                projects = []
            for proj in projects or []:
                self.projects.append(proj)
                self._extract_project_docs(proj)

    @staticmethod
    def _compute_last_run_date(conv_dir: Path) -> Optional[str]:
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

    def _parse_conv(self, data: dict, last_run_date: Optional[str]) -> None:
        conv_id = data.get("id")
        if not conv_id:
            return

        chat = data.get("chat") or {}
        history = chat.get("history") or {}
        messages_dict = history.get("messages") or {}

        # Branches
        current_id = data.get("currentId")
        msg_to_branch, branch_records = build_branches_qwen(
            conv_id, messages_dict, current_id
        )

        # Build messages (na ordem da branch principal primeiro, depois secundarias)
        messages: list[Message] = []
        tool_events: list[ToolEvent] = []
        chat_type = data.get("chat_type") or "t2t"

        # Ordenacao: percorrer todos msgs, sequence baseada em timestamp
        all_msgs = list(messages_dict.values())
        all_msgs.sort(key=lambda m: m.get("timestamp") or 0)

        for seq, msg_data in enumerate(all_msgs, start=1):
            built = self._build_message(
                conv_id, data, msg_data, seq, msg_to_branch, chat_type
            )
            if built is not None:
                messages.append(built)
                tool_events.extend(self._extract_tool_events(conv_id, msg_data, chat_type))

        # Branch records → Branch dataclass
        for br in branch_records:
            self.branches.append(Branch(
                branch_id=br["branch_id"],
                conversation_id=conv_id,
                source=SOURCE,
                root_message_id=br["root_message_id"],
                leaf_message_id=br["leaf_message_id"],
                is_active=br["is_active"],
                created_at=self._ts(_normalize_epoch(br["created_at"])) if br["created_at"] else self._ts(_normalize_epoch(data.get("created_at"))),
                parent_branch_id=br["parent_branch_id"],
            ))

        # Conversation
        last_seen = data.get("_last_seen_in_server")
        is_preserved = bool(data.get("_preserved_missing")) or (
            last_run_date is not None
            and last_seen is not None
            and last_seen < last_run_date
        )

        # Mode mapping
        mode = CHAT_TYPE_TO_MODE.get(chat_type, "chat")
        # archived no schema vem como string 'False' as vezes
        archived_raw = data.get("archived")
        is_archived = archived_raw is True or archived_raw == "True" or archived_raw == True

        # Settings: meta + feature_config (do primeiro msg, se existir)
        first_msg = next(iter(messages_dict.values()), {}) if messages_dict else {}
        settings_json = serialize_settings(
            data.get("meta") or {},
            first_msg.get("feature_config") or {},
        )

        # Model: pega de qualquer msg que tenha (assistant geralmente)
        model = None
        for m in messages_dict.values():
            if m.get("model"):
                model = m["model"]
                break

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=SOURCE,
            title=data.get("title") or None,
            created_at=self._ts(_normalize_epoch(data.get("created_at"))),
            updated_at=self._ts(_normalize_epoch(data.get("updated_at"))),
            message_count=len(messages),
            model=model,
            account=self.account,
            mode=mode,
            project=None,  # nome do project resolvido downstream se necessario
            url=f"https://chat.qwen.ai/c/{conv_id}",
            project_id=(data.get("project_id") or None),  # "" → None
            is_pinned=bool(data.get("pinned", False)),
            is_archived=is_archived,
            is_temporary=False,  # Qwen nao tem feature de temporary chat
            is_preserved_missing=is_preserved,
            last_seen_in_server=self._ts(last_seen) if last_seen else None,
            summary=None,  # Qwen nao gera summary auto
            settings_json=settings_json,
        ))

        self.messages.extend(messages)
        self.events.extend(tool_events)

    def _build_message(
        self,
        conv_id: str,
        conv: dict,
        msg: dict,
        seq: int,
        msg_to_branch: dict[str, str],
        chat_type: str,
    ) -> Optional[Message]:
        role = ROLE_MAP.get(msg.get("role"))
        if role is None:
            return None

        msg_id = msg.get("id") or ""
        content_list = msg.get("content_list") or []

        # Texto: prefere content_list (com timestamps) over content cru
        text_content = collect_text_from_content_list(content_list)
        if not text_content:
            text_content = msg.get("content") or ""

        # Reasoning (R1-equivalente, condicional ao modelo)
        reasoning = msg.get("reasoning_content") or None
        if reasoning == "":
            reasoning = None

        # Files
        files = msg.get("files") or []
        file_names = collect_file_names(files)

        # Block types
        block_types = ["text"] if text_content else []
        if reasoning:
            block_types.append("reasoning")
        if file_names:
            block_types.append("file")
        if msg.get("info") and isinstance(msg["info"], dict) and msg["info"].get("search_results"):
            block_types.append("search")

        # Block timestamps
        start_ts, stop_ts = block_time_bounds(content_list)

        # Model on assistant
        model = msg.get("model") if role == "assistant" else None

        branch_id = msg_to_branch.get(msg_id, f"{conv_id}_main")

        # finish_reason
        is_stop = msg.get("is_stop")
        finish_reason = None
        if is_stop is True:
            finish_reason = "user_stop"
        elif msg.get("error"):
            finish_reason = "error"

        return Message(
            message_id=msg_id,
            conversation_id=conv_id,
            source=SOURCE,
            sequence=seq,
            role=role,
            content=text_content,
            model=model,
            created_at=self._ts(_normalize_epoch(msg.get("timestamp"))) if msg.get("timestamp") else self._ts(_normalize_epoch(conv.get("created_at"))),
            account=self.account,
            attachment_names=json.dumps(file_names, ensure_ascii=False) if file_names else None,
            content_types=",".join(block_types) if block_types else "text",
            thinking=reasoning,
            branch_id=branch_id,
            asset_paths=None,  # Qwen assets nao integrados ainda no parser
            finish_reason=finish_reason,
            citations_json=None,  # search_results vao em ToolEvent, nao em citations
            attachments_json=None,  # Qwen nao tem extracted_content como Claude.ai
            start_timestamp=self._ts(_normalize_epoch(start_ts)) if start_ts else None,
            stop_timestamp=self._ts(_normalize_epoch(stop_ts)) if stop_ts else None,
        )

    def _extract_tool_events(
        self, conv_id: str, msg: dict, chat_type: str
    ) -> list[ToolEvent]:
        """Emite ToolEvent quando msg tem search_results / chat_type especial."""
        events: list[ToolEvent] = []
        msg_id = msg.get("id") or ""

        # Search results (sempre que existir, independente do chat_type)
        results = extract_search_results(msg)
        if results:
            category = CHAT_TYPE_TO_TOOL_CATEGORY.get(chat_type, "search")
            events.append(ToolEvent(
                event_id=f"{msg_id}_search_call",
                conversation_id=conv_id,
                message_id=msg_id,
                source=SOURCE,
                event_type=f"{category}_call",
                tool_name=chat_type,
                metadata_json=json.dumps({
                    "chat_type": chat_type,
                    "sub_chat_type": msg.get("sub_chat_type"),
                    "result_count": len(results),
                }, ensure_ascii=False),
            ))
            events.append(ToolEvent(
                event_id=f"{msg_id}_search_result",
                conversation_id=conv_id,
                message_id=msg_id,
                source=SOURCE,
                event_type=f"{category}_result",
                tool_name=chat_type,
                success=True,
                result=json.dumps(results, ensure_ascii=False),
                metadata_json=json.dumps({"chat_type": chat_type}, ensure_ascii=False),
            ))

        # chat_types especiais sem search (image/video gen, artifacts) — emite event mesmo sem search results
        if chat_type in ("t2i", "t2v", "artifacts") and not results and msg.get("role") == "assistant":
            category = CHAT_TYPE_TO_TOOL_CATEGORY.get(chat_type, "other")
            events.append(ToolEvent(
                event_id=f"{msg_id}_{category}",
                conversation_id=conv_id,
                message_id=msg_id,
                source=SOURCE,
                event_type=f"{category}_call",
                tool_name=chat_type,
                metadata_json=json.dumps({
                    "chat_type": chat_type,
                    "sub_chat_type": msg.get("sub_chat_type"),
                }, ensure_ascii=False),
            ))

        return events

    def _extract_project_docs(self, proj: dict) -> None:
        """Extrai files do project como ProjectDoc.

        Qwen project files moram em `_files` (injetado pelo extractor) com
        `file_id`, `file_name`, `path` (S3 presigned URL), `size`, `file_type`.
        Diferente do Claude.ai (que tem content inline), Qwen so retorna URL —
        content fica externo. Marcamos content="" mas preservamos size + URL
        em metadata.
        """
        proj_id = proj.get("id")
        if not proj_id:
            return
        for f in proj.get("_files") or []:
            if not isinstance(f, dict):
                continue
            doc_id = f.get("file_id") or f.get("id")
            if not doc_id:
                continue
            self.project_docs.append(ProjectDoc(
                doc_id=doc_id,
                project_id=proj_id,
                source=SOURCE,
                file_name=f.get("file_name") or f.get("name") or "",
                content="",  # Qwen retorna URL S3, content nao inline
                content_size=int(f.get("size") or 0),
                estimated_token_count=None,
                created_at=self._ts(_normalize_epoch(f.get("created_at"))) if f.get("created_at") else None,
            ))

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def project_docs_df(self) -> pd.DataFrame:
        return project_docs_to_df(self.project_docs)

    def project_metadata_df(self) -> pd.DataFrame:
        if not self.projects:
            return pd.DataFrame(columns=[
                "project_id", "name", "icon", "custom_instruction",
                "memory_span", "created_at", "updated_at", "files_count",
            ])
        rows = []
        for p in self.projects:
            files = p.get("_files") or []
            rows.append({
                "project_id": p.get("id"),
                "name": p.get("name", ""),
                "icon": p.get("icon", ""),
                "custom_instruction": p.get("custom_instruction", ""),
                "memory_span": p.get("memory_span", ""),
                "created_at": self._ts(_normalize_epoch(p.get("created_at"))),
                "updated_at": self._ts(_normalize_epoch(p.get("updated_at"))),
                "files_count": len(files),
            })
        return pd.DataFrame(rows)

    def save(self, output_dir: Path) -> None:
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
