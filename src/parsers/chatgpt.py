"""Parser canonico do ChatGPT — consome chatgpt_merged.json e gera parquets.

Cobertura:
- Tree-walk completo do mapping (preserva branches off-path)
- Voice (com direction), DALL-E em ToolEvent, uploads em Message, tether_quote,
  canvas, deep_research, custom_gpt vs project, tools (role=tool -> ToolEvent)
- Preservation (is_preserved_missing, last_seen_in_server) derivados de
  _last_seen_in_server vs max conhecido no merged

Output: data/processed/ChatGPT/{conversations,messages,tool_events,branches}.parquet

Historico: veio do parser v3 (validado em 2026-04-28). Versoes anteriores
(chatgpt_v2 MVP, chatgpt legacy GPT2Claude bookmarklet) ficaram em
_backup-temp/parser-v3-promocao-2026-04-28/ pra rollback se necessario.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers.base import BaseParser
from src.parsers._chatgpt_helpers import (
    classify_event_type,
    detect_canvas_signal,
    detect_deep_research_signal,
    detect_hidden,
    detect_voice,
    extract_finish_reason,
    extract_image_asset_pointers,
    extract_text,
    is_custom_gpt_gizmo_id,
    is_project_gizmo_id,
    resolve_asset_path,
)
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


class ChatGPTParser(BaseParser):
    source_name = "chatgpt"

    def __init__(self, account: Optional[str] = None, raw_root: Optional[Path] = None):
        super().__init__(account)
        self.raw_root = Path(raw_root) if raw_root else Path("data/raw/ChatGPT")

    def reset(self):
        super().reset()
        self.branches: list[Branch] = []

    @property
    def assets_root(self) -> Path:
        return self.raw_root / "assets"

    def parse(self, input_path: Path) -> None:
        with open(input_path, encoding="utf-8") as f:
            raw = json.load(f)

        convs = raw.get("conversations") or {}
        if not isinstance(convs, dict):
            raise ValueError(
                f"Esperado dict em 'conversations', recebido {type(convs).__name__}. "
                "Parser v3 consome chatgpt_merged.json (output do reconciler)."
            )

        last_run_date = self._compute_last_run_date(convs)

        for conv_id, conv_data in convs.items():
            self._extract_conv(conv_id, conv_data, last_run_date)

    @staticmethod
    def _compute_last_run_date(convs: dict) -> Optional[str]:
        """Maior _last_seen_in_server no merged. Usado pra derivar is_preserved_missing
        de forma idempotente (independente da data atual)."""
        seens = [c.get("_last_seen_in_server") for c in convs.values() if c.get("_last_seen_in_server")]
        return max(seens) if seens else None

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def _extract_branches(
        self, conv_id: str, conv_data: dict,
    ) -> tuple[list[Branch], dict[str, str]]:
        """Identifica branches via DFS do mapping inteiro.

        Algoritmo (plan §4.1):
        - Root = node sem parent (ou parent fora do mapping)
        - Main branch = root ate o primeiro fork
        - Fork (>=2 children): cada child comeca uma sub-branch
        - is_active: branch contem current_node
        - Convencao branch_id: '<conv>_main' pra principal; '<conv>_<node_root>' pra forks

        Retorna (lista de Branch, msg_to_branch dict).
        """
        mapping = conv_data.get("mapping") or {}
        current_node = conv_data.get("current_node")
        if not mapping:
            return [], {}

        # Acha root: node sem parent ou cujo parent nao esta no mapping
        roots = [
            nid for nid, n in mapping.items()
            if not n.get("parent") or n.get("parent") not in mapping
        ]
        if not roots:
            return [], {}
        root = roots[0]

        # Estado mutavel das branches em construcao
        branch_meta: dict[str, dict] = {}
        msg_to_branch: dict[str, str] = {}

        def _new_branch(branch_id: str, root_node: str, parent_branch: Optional[str]) -> None:
            msg = (mapping.get(root_node) or {}).get("message") or {}
            branch_meta[branch_id] = {
                "branch_id": branch_id,
                "conversation_id": conv_id,
                "root_message_id": root_node,
                "leaf_message_id": root_node,
                "created_at": (
                    self._ts(msg.get("create_time"))
                    if msg.get("create_time") is not None else pd.NaT
                ),
                "parent_branch_id": parent_branch,
            }

        main_branch_id = f"{conv_id}_main"
        _new_branch(main_branch_id, root, None)

        # DFS iterativo. Stack: (node_id, branch_id).
        # Reverse children pra visitar em ordem natural (stack LIFO).
        stack: list[tuple[str, str]] = [(root, main_branch_id)]
        while stack:
            node_id, branch_id = stack.pop()
            if node_id in msg_to_branch:
                continue
            msg_to_branch[node_id] = branch_id
            branch_meta[branch_id]["leaf_message_id"] = node_id

            children = (mapping.get(node_id) or {}).get("children") or []
            valid_children = [c for c in children if c in mapping]

            if len(valid_children) >= 2:
                # Fork: cada child vira sub-branch
                for child_id in reversed(valid_children):
                    sub_id = f"{conv_id}_{child_id}"
                    if sub_id not in branch_meta:
                        _new_branch(sub_id, child_id, branch_id)
                    stack.append((child_id, sub_id))
            elif len(valid_children) == 1:
                stack.append((valid_children[0], branch_id))

        active_branch_id = msg_to_branch.get(current_node) if current_node else None

        branch_objs = [
            Branch(
                branch_id=b["branch_id"],
                conversation_id=b["conversation_id"],
                source=self.source_name,
                root_message_id=b["root_message_id"],
                leaf_message_id=b["leaf_message_id"],
                is_active=(b["branch_id"] == active_branch_id),
                created_at=b["created_at"],
                parent_branch_id=b["parent_branch_id"],
            )
            for b in branch_meta.values()
        ]
        # Ordem deterministica (idempotencia): main primeiro, depois pelo created_at, depois branch_id
        branch_objs.sort(key=lambda b: (
            0 if b.parent_branch_id is None else 1,
            b.created_at if not pd.isna(b.created_at) else pd.Timestamp("1970-01-01"),
            b.branch_id,
        ))
        return branch_objs, msg_to_branch

    # ------------------------------------------------------------------
    # Conversation processing
    # ------------------------------------------------------------------

    def _extract_conv(self, conv_id: str, conv_data: dict, last_run_date: Optional[str]) -> None:
        mapping = conv_data.get("mapping") or {}
        if not mapping:
            return

        branches, msg_to_branch = self._extract_branches(conv_id, conv_data)
        if not branches:
            return

        # Itera todos os nodes do mapping (nao so path linear).
        # Ordem deterministica: por (branch_id, create_time, node_id) — garante
        # idempotencia e sequence cronologica dentro da branch.
        nodes_with_meta = []
        for node_id, node in mapping.items():
            if node_id not in msg_to_branch:
                continue
            msg = node.get("message")
            if not msg:
                continue
            ct = msg.get("create_time")
            nodes_with_meta.append((
                msg_to_branch[node_id],
                ct if ct is not None else 0,
                node_id,
                node,
                msg,
            ))
        nodes_with_meta.sort(key=lambda x: (x[0], x[1], x[2]))

        messages: list[Message] = []
        tool_events: list[ToolEvent] = []
        last_assistant_model: Optional[str] = None
        seq = 0
        evt_seq = 0

        for branch_id, _ct, node_id, node, msg in nodes_with_meta:
            parent_id = node.get("parent") or ""
            author = msg.get("author") or {}
            role = author.get("role")
            content = msg.get("content") or {}
            ctype = content.get("content_type") or "text"
            metadata = msg.get("metadata") or {}

            # ToolEvent pra tether_quote (content_type proprio)
            if ctype == "tether_quote":
                evt_seq += 1
                tool_events.append(self._build_tether_quote_event(
                    msg=msg, conv_id=conv_id, parent_id=parent_id, evt_seq=evt_seq,
                ))
                continue

            # role=tool -> ToolEvent (independente de content_type)
            if role == "tool":
                evt_seq += 1
                tool_events.append(self._build_tool_event(
                    msg=msg, conv_id=conv_id, parent_id=parent_id, evt_seq=evt_seq,
                ))
                continue

            # Canvas/DR como Message do assistant: tambem geram ToolEvent extra
            if role == "assistant" and detect_canvas_signal(msg):
                evt_seq += 1
                tool_events.append(self._build_canvas_event(
                    msg=msg, conv_id=conv_id, parent_id=parent_id, evt_seq=evt_seq,
                ))
            elif role == "assistant" and detect_deep_research_signal(msg):
                evt_seq += 1
                tool_events.append(self._build_deep_research_event(
                    msg=msg, conv_id=conv_id, parent_id=parent_id, evt_seq=evt_seq,
                ))

            if role not in ("user", "assistant"):
                continue

            text = extract_text(content)
            is_voice, voice_dir = detect_voice(content)

            asset_paths: Optional[list[str]] = None
            image_pointers = extract_image_asset_pointers(content)
            has_dalle = any(is_dalle for _, is_dalle in image_pointers)
            if image_pointers:
                resolved = []
                for ap, _ in image_pointers:
                    p = resolve_asset_path(ap, conv_id, self.assets_root)
                    if p:
                        resolved.append(p)
                asset_paths = resolved or None

            if not text and not asset_paths and not is_voice:
                continue

            markers = [ctype]
            if is_voice:
                markers.append("audio_transcription")
            if has_dalle:
                markers.append("dalle")
            elif image_pointers:
                markers.append("image_upload")
            content_types_csv = ",".join(markers)

            model_slug = metadata.get("model_slug")
            if role == "assistant" and model_slug:
                last_assistant_model = model_slug

            is_hidden, hidden_reason = detect_hidden(msg)
            finish_reason = extract_finish_reason(metadata)

            seq += 1
            messages.append(Message(
                message_id=msg.get("id") or f"{conv_id}_{seq}",
                conversation_id=conv_id,
                source=self.source_name,
                sequence=seq,
                role=role,
                content=text,
                model=model_slug if role == "assistant" else None,
                created_at=self._ts(msg.get("create_time")),
                account=self.account,
                content_types=content_types_csv,
                branch_id=branch_id,
                asset_paths=asset_paths,
                finish_reason=finish_reason,
                is_hidden=is_hidden,
                hidden_reason=hidden_reason,
                is_voice=is_voice,
                voice_direction=voice_dir,
            ))

        if not messages and not tool_events:
            return

        # message_count: msgs visiveis na branch ativa (pra ser comparable com dashboard)
        active_branch_ids = {b.branch_id for b in branches if b.is_active}
        if active_branch_ids:
            visible_count = sum(
                1 for m in messages
                if not m.is_hidden and m.branch_id in active_branch_ids
            )
        else:
            visible_count = sum(1 for m in messages if not m.is_hidden)

        gizmo_id_raw = conv_data.get("gizmo_id")
        project_id, conv_gizmo_id, gizmo_resolved = self._classify_gizmo(gizmo_id_raw, conv_data)

        last_seen_str = conv_data.get("_last_seen_in_server")
        last_seen_ts = self._ts(last_seen_str) if last_seen_str else pd.NaT
        is_preserved_missing = bool(
            last_run_date and last_seen_str and last_seen_str != last_run_date
        )

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=self.source_name,
            title=conv_data.get("title") or None,
            created_at=self._ts(conv_data.get("create_time")),
            updated_at=self._ts(conv_data.get("update_time")),
            message_count=visible_count,
            model=last_assistant_model,
            account=self.account,
            mode="chat",
            project=conv_data.get("_project_name") or None,
            url=f"https://chatgpt.com/c/{conv_id}",
            project_id=project_id,
            gizmo_id=conv_gizmo_id,
            gizmo_name=None,
            gizmo_resolved=gizmo_resolved,
            is_preserved_missing=is_preserved_missing,
            last_seen_in_server=last_seen_ts if not pd.isna(last_seen_ts) else None,
        ))
        self.messages.extend(messages)
        self.events.extend(tool_events)
        self.branches.extend(branches)

    @staticmethod
    def _classify_gizmo(gizmo_id_raw: Optional[str], conv_data: dict) -> tuple[Optional[str], Optional[str], bool]:
        if not gizmo_id_raw:
            project_id = conv_data.get("_project_id") or None
            return project_id, None, True
        if is_project_gizmo_id(gizmo_id_raw):
            return gizmo_id_raw, None, True
        if is_custom_gpt_gizmo_id(gizmo_id_raw):
            return conv_data.get("_project_id") or None, gizmo_id_raw, True
        return conv_data.get("_project_id") or None, gizmo_id_raw, False

    # ------------------------------------------------------------------
    # Event builders
    # ------------------------------------------------------------------

    def _build_tether_quote_event(
        self, *, msg: dict, conv_id: str, parent_id: str, evt_seq: int,
    ) -> ToolEvent:
        content = msg.get("content") or {}
        meta_payload = {
            k: content.get(k)
            for k in ("url", "domain", "title")
            if content.get(k)
        }
        return ToolEvent(
            event_id=f"{conv_id}_evt_{evt_seq}",
            conversation_id=conv_id,
            message_id=parent_id,
            source=self.source_name,
            event_type="quote",
            tool_name="tether_quote",
            result=content.get("text") or None,
            metadata_json=json.dumps(meta_payload, ensure_ascii=False) if meta_payload else None,
        )

    def _build_tool_event(
        self, *, msg: dict, conv_id: str, parent_id: str, evt_seq: int,
    ) -> ToolEvent:
        author = msg.get("author") or {}
        tool_name = author.get("name")
        content = msg.get("content") or {}
        result = extract_text(content) or None
        metadata = msg.get("metadata") or {}

        file_path: Optional[str] = None
        has_dalle = False
        for ap, is_dalle in extract_image_asset_pointers(content):
            if is_dalle:
                has_dalle = True
            resolved = resolve_asset_path(ap, conv_id, self.assets_root)
            if resolved and not file_path:
                file_path = resolved

        event_type = "image_generation" if has_dalle else classify_event_type(tool_name)

        return ToolEvent(
            event_id=f"{conv_id}_evt_{evt_seq}",
            conversation_id=conv_id,
            message_id=parent_id,
            source=self.source_name,
            event_type=event_type,
            tool_name=tool_name,
            file_path=file_path,
            result=result,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
        )

    def _build_canvas_event(
        self, *, msg: dict, conv_id: str, parent_id: str, evt_seq: int,
    ) -> ToolEvent:
        recipient = msg.get("recipient") or ""
        author = msg.get("author") or {}
        tool_name = recipient if recipient.startswith("canmore.") else (author.get("name") or "canmore")
        content = msg.get("content") or {}
        return ToolEvent(
            event_id=f"{conv_id}_evt_{evt_seq}",
            conversation_id=conv_id,
            message_id=parent_id,
            source=self.source_name,
            event_type="canvas",
            tool_name=tool_name,
            result=extract_text(content) or None,
            metadata_json=json.dumps(msg.get("metadata") or {}, ensure_ascii=False) or None,
        )

    def _build_deep_research_event(
        self, *, msg: dict, conv_id: str, parent_id: str, evt_seq: int,
    ) -> ToolEvent:
        recipient = msg.get("recipient") or ""
        author = msg.get("author") or {}
        tool_name = (
            recipient if recipient.startswith("research_kickoff_tool")
            else (author.get("name") or "research_kickoff_tool")
        )
        content = msg.get("content") or {}
        return ToolEvent(
            event_id=f"{conv_id}_evt_{evt_seq}",
            conversation_id=conv_id,
            message_id=parent_id,
            source=self.source_name,
            event_type="deep_research",
            tool_name=tool_name,
            result=extract_text(content) or None,
            metadata_json=json.dumps(msg.get("metadata") or {}, ensure_ascii=False) or None,
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def save(self, output_dir: Path) -> None:
        """Override de BaseParser.save — paths sem prefix de source.

        Layout (plan §5):
            <output_dir>/conversations.parquet
            <output_dir>/messages.parquet
            <output_dir>/tool_events.parquet
            <output_dir>/branches.parquet
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        conv_df = conversations_to_df(self.conversations)
        if not conv_df.empty:
            conv_df.to_parquet(output_dir / "conversations.parquet", index=False)

        msg_df = messages_to_df(self.messages)
        if not msg_df.empty:
            msg_df["word_count"] = msg_df["content"].fillna("").str.split().str.len()
            msg_df.to_parquet(output_dir / "messages.parquet", index=False)

        evt_df = tool_events_to_df(self.events)
        if not evt_df.empty:
            evt_df.to_parquet(output_dir / "tool_events.parquet", index=False)

        br_df = self.branches_df()
        if not br_df.empty:
            br_df.to_parquet(output_dir / "branches.parquet", index=False)
