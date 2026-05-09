"""Parser canonico do Grok — schema v3.

Consome merged em data/merged/Grok/conversations/<uuid>.json (envelope com
conversation_v2 + response_node + responses + files + share_links) +
workspaces.json. Gera parquets canonicos.

Cobertura (probe + smoke 2026-05-09):
- Conversation: meta de conversation_v2.conversation
- Workspace (project): conv_v2.workspaces[*] -> ConversationProject
- Workspace metadata: workspaces.json -> grok_workspace_metadata.parquet
- Message: cada response em responses.responses
  - sender: 'human' -> 'user', 'assistant'/'ASSISTANT' -> 'assistant'
  - model: response.model (grok-3, grok-4-auto, etc)
  - thinking: nao exposto (Grok nao retorna chain-of-thought no schema atual)
- ToolEvent: emit por response quando tem search/rag/connector/image/xpost/tool
- Branches: response_node retorna ordering plano em V1 — sem branch detection
  (response-node retorna threads quando alternative paths existem; deferred).

Output: data/processed/Grok/grok_{conversations,messages,tool_events,
workspace_metadata,conversation_projects}.parquet
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import (
    Conversation,
    ConversationProject,
    Message,
    ToolEvent,
    conversation_projects_to_df,
    conversations_to_df,
    messages_to_df,
    tool_events_to_df,
)


SOURCE = "grok"


def _role(sender: str) -> Optional[str]:
    if not sender:
        return None
    s = sender.strip().lower()
    if s == "human":
        return "user"
    if s == "assistant":
        return "assistant"
    return None


def _has_items(value) -> bool:
    return isinstance(value, list) and len(value) > 0


class GrokParser(BaseParser):
    source_name = SOURCE

    def __init__(
        self,
        account: Optional[str] = None,
        merged_root: Optional[Path] = None,
    ):
        super().__init__(account)
        self.merged_root = Path(merged_root) if merged_root else Path("data/merged/Grok")
        self.workspaces: list[dict] = []
        self.assets: list[dict] = []
        self.scheduled_tasks: dict = {}
        self.conversation_projects: list[ConversationProject] = []

    def reset(self):
        super().reset()
        self.workspaces = []
        self.assets = []
        self.scheduled_tasks = {}
        self.conversation_projects = []

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
            self._parse_envelope(envelope)
        else:
            raise FileNotFoundError(f"Input nao existe: {input_path}")

    def _parse_merged_dir(self, merged_root: Path) -> None:
        self.merged_root = merged_root
        conv_dir = merged_root / "conversations"
        if conv_dir.exists():
            for fp in sorted(conv_dir.glob("*.json")):
                try:
                    with open(fp, encoding="utf-8") as f:
                        envelope = json.load(f)
                except Exception:
                    continue
                self._parse_envelope(envelope)

        ws_path = merged_root / "workspaces.json"
        if ws_path.exists():
            try:
                self.workspaces = json.loads(ws_path.read_text(encoding="utf-8")) or []
            except Exception:
                self.workspaces = []

        assets_path = merged_root / "assets.json"
        if assets_path.exists():
            try:
                self.assets = json.loads(assets_path.read_text(encoding="utf-8")) or []
            except Exception:
                self.assets = []

        tasks_path = merged_root / "tasks.json"
        if tasks_path.exists():
            try:
                self.scheduled_tasks = json.loads(tasks_path.read_text(encoding="utf-8")) or {}
            except Exception:
                self.scheduled_tasks = {}

    def _parse_envelope(self, envelope: dict) -> None:
        conv = (envelope.get("conversation_v2") or {}).get("conversation") or {}
        conv_id = conv.get("conversationId")
        if not conv_id:
            return

        responses = (envelope.get("responses") or {}).get("responses") or []
        # Ordena por createTime (string ISO ordena lexicograficamente)
        responses = sorted(responses, key=lambda r: r.get("createTime") or "")

        # Workspaces (projects) da conv
        conv_workspaces = conv.get("workspaces") or []
        # Modelo: ultimo assistant que tenha campo model setado
        model = None
        for r in reversed(responses):
            if _role(r.get("sender")) == "assistant" and r.get("model"):
                model = r.get("model")
                break
        if not model:
            for r in responses:
                if r.get("model"):
                    model = r.get("model")
                    break

        # Build messages + tool events
        msgs: list[Message] = []
        events: list[ToolEvent] = []
        for seq, r in enumerate(responses, start=1):
            built = self._build_message(conv_id, conv, r, seq)
            if built is not None:
                msgs.append(built)
                events.extend(self._extract_tool_events(conv_id, r))

        # Conversation
        is_preserved = bool(envelope.get("_preserved_missing"))
        last_seen = envelope.get("_last_seen_in_server")

        # First/last response timestamps as fallback se conv.createTime/modifyTime ausente
        created_at = conv.get("createTime")
        updated_at = conv.get("modifyTime")
        if not created_at and responses:
            created_at = responses[0].get("createTime")
        if not updated_at and responses:
            updated_at = responses[-1].get("createTime")

        # Settings: conversa-level metadata leve
        settings = {
            "systemPromptName": conv.get("systemPromptName") or "",
            "mediaTypes": conv.get("mediaTypes") or [],
            "taskResult": conv.get("taskResult") or {},
        }
        settings_json = (
            json.dumps(settings, ensure_ascii=False)
            if any(settings.values())
            else None
        )

        primary_workspace_id = None
        primary_workspace_name = None
        if conv_workspaces:
            primary_workspace_id = conv_workspaces[0].get("workspaceId")
            primary_workspace_name = conv_workspaces[0].get("name")

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=SOURCE,
            title=conv.get("title") or None,
            created_at=self._ts(created_at),
            updated_at=self._ts(updated_at),
            message_count=len(msgs),
            model=model,
            account=self.account,
            mode="chat",
            project=primary_workspace_name,
            url=f"https://grok.com/c/{conv_id}",
            project_id=primary_workspace_id,
            is_pinned=bool(conv.get("starred", False)),
            is_archived=None,
            is_temporary=bool(conv.get("temporary", False)),
            is_preserved_missing=is_preserved,
            last_seen_in_server=self._ts(last_seen) if last_seen else None,
            settings_json=settings_json,
        ))
        self.messages.extend(msgs)
        self.events.extend(events)

        # ConversationProject: 1 por workspace
        for ws in conv_workspaces:
            wid = ws.get("workspaceId")
            if not wid:
                continue
            self.conversation_projects.append(ConversationProject(
                conversation_id=conv_id,
                project_tag=wid,
                tagged_by="grok_workspace",
                source=SOURCE,
            ))

    def _build_message(
        self, conv_id: str, conv: dict, r: dict, seq: int
    ) -> Optional[Message]:
        role = _role(r.get("sender"))
        if role is None:
            return None

        msg_id = r.get("responseId") or ""
        text = r.get("message") or ""

        # Block types
        block_types: list[str] = []
        if text:
            block_types.append("text")
        if _has_items(r.get("webSearchResults")) or _has_items(r.get("citedWebSearchResults")):
            block_types.append("search")
        if _has_items(r.get("xposts")) or _has_items(r.get("citedXposts")):
            block_types.append("xpost")
        if _has_items(r.get("ragResults")) or _has_items(r.get("citedRagResults")):
            block_types.append("rag")
        if _has_items(r.get("generatedImageUrls")) or _has_items(r.get("imageEditUris")):
            block_types.append("image_gen")
        if _has_items(r.get("imageAttachments")) or _has_items(r.get("fileAttachments")) or _has_items(r.get("fileUris")):
            block_types.append("attachment")
        if _has_items(r.get("toolResponses")):
            block_types.append("tool")

        # Attachment names
        attachment_names: list[str] = []
        for a in r.get("imageAttachments") or []:
            n = (a.get("name") if isinstance(a, dict) else None) or ""
            if n:
                attachment_names.append(n)
        for a in r.get("fileAttachments") or []:
            n = (a.get("name") if isinstance(a, dict) else None) or ""
            if n:
                attachment_names.append(n)
        # fileUris pode ser list de str
        for u in r.get("fileUris") or []:
            if isinstance(u, str) and u:
                attachment_names.append(u.rsplit("/", 1)[-1])

        finish_reason = None
        if r.get("partial"):
            finish_reason = "partial"
        if _has_items(r.get("streamErrors")):
            finish_reason = "stream_error"

        model = r.get("model") if role == "assistant" else None

        return Message(
            message_id=msg_id,
            conversation_id=conv_id,
            source=SOURCE,
            sequence=seq,
            role=role,
            content=text,
            model=model,
            created_at=self._ts(r.get("createTime")),
            account=self.account,
            attachment_names=json.dumps(attachment_names, ensure_ascii=False) if attachment_names else None,
            content_types=",".join(block_types) if block_types else "text",
            thinking=None,
            branch_id=f"{conv_id}_main",
            finish_reason=finish_reason,
            is_hidden=bool(r.get("isControl")),
        )

    def _extract_tool_events(self, conv_id: str, r: dict) -> list[ToolEvent]:
        events: list[ToolEvent] = []
        msg_id = r.get("responseId") or ""

        def emit(category: str, items: list, key: str):
            if not items:
                return
            events.append(ToolEvent(
                event_id=f"{msg_id}_{key}",
                conversation_id=conv_id,
                message_id=msg_id,
                source=SOURCE,
                event_type=f"{category}_result",
                tool_name=key,
                success=True,
                result=json.dumps(items, ensure_ascii=False),
                metadata_json=json.dumps({"count": len(items)}, ensure_ascii=False),
            ))

        emit("search", r.get("webSearchResults") or [], "web_search")
        emit("search", r.get("citedWebSearchResults") or [], "cited_web_search")
        emit("xpost", r.get("xposts") or [], "xposts")
        emit("xpost", r.get("citedXposts") or [], "cited_xposts")
        emit("rag", r.get("ragResults") or [], "rag")
        emit("rag", r.get("citedRagResults") or [], "cited_rag")
        emit("connector", r.get("connectorSearchResults") or [], "connector_search")
        emit("connector", r.get("citedConnectorSearchResults") or [], "cited_connector_search")
        emit("collection", r.get("collectionSearchResults") or [], "collection_search")
        emit("collection", r.get("citedCollectionSearchResults") or [], "cited_collection_search")
        emit("product", r.get("searchProductResults") or [], "product_search")
        emit("image", r.get("generatedImageUrls") or [], "image_gen")
        emit("tool", r.get("toolResponses") or [], "tool_response")
        return events

    def conversation_projects_df(self) -> pd.DataFrame:
        return conversation_projects_to_df(self.conversation_projects)

    def assets_df(self) -> pd.DataFrame:
        if not self.assets:
            return pd.DataFrame(columns=[
                "asset_id", "mime_type", "name", "size_bytes",
                "key", "file_source", "is_model_generated",
                "is_root_asset_created_by_model", "is_latest", "is_deleted",
                "shared_with_team", "is_public", "root_asset_id",
                "inline_status", "summary", "preview_image_key",
                "is_preserved_missing", "created_at", "last_use_time",
            ])
        rows = []
        for a in self.assets:
            rows.append({
                "asset_id": a.get("assetId"),
                "mime_type": a.get("mimeType") or "",
                "name": a.get("name") or "",
                "size_bytes": int(a.get("sizeBytes") or 0),
                "key": a.get("key") or "",
                "file_source": a.get("fileSource") or "",
                "is_model_generated": bool(a.get("isModelGenerated", False)),
                "is_root_asset_created_by_model": bool(a.get("isRootAssetCreatedByModel", False)),
                "is_latest": bool(a.get("isLatest", False)),
                "is_deleted": bool(a.get("isDeleted", False)),
                "shared_with_team": bool(a.get("sharedWithTeam", False)),
                "is_public": bool(a.get("isPublic", False)),
                "root_asset_id": a.get("rootAssetId") or "",
                "inline_status": a.get("inlineStatus") or "",
                "summary": a.get("summary") or "",
                "preview_image_key": a.get("previewImageKey") or "",
                "is_preserved_missing": bool(a.get("_preserved_missing", False)),
                "created_at": self._ts(a.get("createTime")),
                "last_use_time": self._ts(a.get("lastUseTime")),
            })
        return pd.DataFrame(rows)

    def scheduled_tasks_df(self) -> pd.DataFrame:
        """Scheduled tasks (active + inactive). Schema preliminar inferido —
        endpoint retornou tasks vazias no probe, parser tolera extras."""
        all_tasks: list[dict] = []
        for t in (self.scheduled_tasks.get("active") or []):
            all_tasks.append({**t, "_status": "active"})
        for t in (self.scheduled_tasks.get("inactive") or []):
            all_tasks.append({**t, "_status": "inactive"})
        if not all_tasks:
            return pd.DataFrame()
        # Mantem tudo como JSON-friendly: dict bruto + status flag
        return pd.DataFrame(all_tasks)

    def project_metadata_df(self) -> pd.DataFrame:
        """Workspace (project) metadata. Schema alinhado com Qwen project_metadata
        (project_id, name, icon, custom_instruction, created_at, updated_at) +
        campos especificos do Grok (preferred_model, view_count, etc)."""
        if not self.workspaces:
            return pd.DataFrame(columns=[
                "project_id", "name", "icon", "custom_instruction",
                "preferred_model", "is_public", "access_level",
                "view_count", "conversations_created_count", "clone_count",
                "is_preserved_missing", "created_at", "updated_at",
            ])
        rows = []
        for w in self.workspaces:
            detail = w.get("_detail") or w
            rows.append({
                "project_id": w.get("workspaceId"),
                "name": w.get("name") or "",
                "icon": w.get("icon") or "",
                "custom_instruction": detail.get("customPersonality") or "",
                "preferred_model": detail.get("preferredModel") or "",
                "is_public": bool(detail.get("isPublic", False)),
                "access_level": detail.get("accessLevel") or "",
                "view_count": int(detail.get("viewCount") or 0),
                "conversations_created_count": int(detail.get("conversationsCreatedCount") or 0),
                "clone_count": int(detail.get("cloneCount") or 0),
                "is_preserved_missing": bool(w.get("_preserved_missing", False)),
                "created_at": self._ts(w.get("createTime")),
                "updated_at": self._ts(w.get("lastUseTime")),
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

        cp_df = self.conversation_projects_df()
        if not cp_df.empty:
            cp_df.to_parquet(output_dir / f"{self.source_name}_conversation_projects.parquet")

        ws_df = self.project_metadata_df()
        if not ws_df.empty:
            ws_df.to_parquet(output_dir / f"{self.source_name}_project_metadata.parquet")

        as_df = self.assets_df()
        if not as_df.empty:
            as_df.to_parquet(output_dir / f"{self.source_name}_assets.parquet")

        tk_df = self.scheduled_tasks_df()
        if not tk_df.empty:
            tk_df.to_parquet(output_dir / f"{self.source_name}_scheduled_tasks.parquet")
