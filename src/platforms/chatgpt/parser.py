"""Parser canonico do ChatGPT — consome chatgpt_merged.json e gera parquets.

Cobertura:
- Tree-walk completo do mapping (preserva branches off-path)
- Voice (com direction), DALL-E em ToolEvent, uploads em Message, tether_quote,
  canvas, deep_research, custom_gpt vs project, tools (role=tool -> ToolEvent)
- Preservation (is_preserved_missing, last_seen_in_server) derivados de
  _last_seen_in_server vs max conhecido no merged
- Account saved memories, summaries and instructions with versions and temporal evidence

Output: source-prefixed conversation/asset Parquets and the three versioned
agent-memory tables under data/processed/ChatGPT/.

Historico: veio do parser v3, validado em 2026-04-28. As versoes anteriores
(chatgpt_v2 MVP e chatgpt legacy GPT2Claude bookmarklet) foram supersedidas
nessa promocao.
"""

from __future__ import annotations

import json
import hashlib
import mimetypes
from pathlib import Path
from typing import Optional

import pandas as pd

from src.assets.reader import AssetReader
from src.parsing.base import BaseParser
from src.platforms.chatgpt.memory_parser import parse_account_memory
from src.platforms.chatgpt.project_settings_parser import parse_project_instructions
from src.platforms.chatgpt._parser_helpers import (
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
    parse_asset_pointer,
    resolve_asset_path,
)
from src.schema.models import (
    Asset,
    AssetLink,
    Branch,
    Conversation,
    Message,
    ToolEvent,
    agent_memories_to_df,
    agent_memory_versions_to_df,
    agent_memory_temporal_evidence_to_df,
    asset_links_to_df,
    assets_to_df,
    branches_to_df,
    conversations_to_df,
    make_asset_link_id,
    messages_to_df,
    tool_events_to_df,
)


class ChatGPTParser(BaseParser):
    source_name = "chatgpt"

    def __init__(self, account: Optional[str] = None, raw_root: Optional[Path] = None,
                 account_id: Optional[str] = None, *,
                 asset_reader: AssetReader | None = None):
        super().__init__(account, account_id, asset_reader=asset_reader)
        self.raw_root = Path(raw_root) if raw_root else Path("data/raw/ChatGPT")

    def reset(self):
        super().reset()
        self.branches: list[Branch] = []
        self.assets: list[Asset] = []
        self.asset_links: list[AssetLink] = []
        self._assets_by_id: dict[str, Asset] = {}
        self._asset_link_ids: set[str] = set()
        self.agent_memories = []
        self.agent_memory_versions = []
        self.agent_memory_temporal_evidence = []

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
        self._record_preserved_file_assets()
        self.apply_asset_reader()
        self.parse_account_memory()

    def parse_account_memory(self) -> None:
        result = parse_account_memory(self.raw_root, self.account_id)
        projects = parse_project_instructions(self.raw_root, self.account_id)
        self.agent_memories = result.memories + projects.memories
        self.agent_memory_versions = result.versions + projects.versions
        self.agent_memory_temporal_evidence = result.temporal_evidence + projects.temporal_evidence

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
                account_id=self.account_id,
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
        asset_link_start = len(self.asset_links)

        for branch_id, _ct, node_id, node, msg in nodes_with_meta:
            parent_id = node.get("parent") or ""
            author = msg.get("author") or {}
            role = author.get("role")
            content = msg.get("content") or {}
            ctype = content.get("content_type") or "text"
            metadata = msg.get("metadata") or {}

            if role in ("user", "assistant", "tool"):
                self._record_image_assets(
                    msg=msg,
                    conv_id=conv_id,
                    canonical_message_id=(parent_id if role == "tool" else (msg.get("id") or node_id)),
                    role=role,
                )

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
                account_id=self.account_id,
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
            del self.asset_links[asset_link_start:]
            self._asset_link_ids = {link.asset_link_id for link in self.asset_links}
            return

        self._repair_asset_link_targets(
            conv_id, mapping, {message.message_id for message in messages}, asset_link_start,
        )

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
            account_id=self.account_id,
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
            is_archived=bool(conv_data.get("is_archived")) if conv_data.get("is_archived") is not None else None,
            is_temporary=bool(conv_data.get("is_temporary_chat")) if conv_data.get("is_temporary_chat") is not None else None,
            is_pinned=bool(conv_data.get("is_starred")) if conv_data.get("is_starred") is not None else None,
        ))
        self.messages.extend(messages)
        self.events.extend(tool_events)
        self.branches.extend(branches)

    def _data_relative_asset_path(self, path: Path) -> str:
        for parent in (path, *path.parents):
            if parent.name == "data":
                return path.relative_to(parent).as_posix()
        return (Path("raw/ChatGPT") / path.relative_to(self.raw_root)).as_posix()

    @staticmethod
    def _mime_type(path: Path) -> Optional[str]:
        guessed = mimetypes.guess_type(path.name)[0]
        if guessed:
            return guessed
        try:
            prefix = path.read_bytes()[:12]
        except OSError:
            return None
        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if prefix.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if prefix.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
            return "image/webp"
        return None

    def _add_preserved_asset(
        self, *, asset_id: str, path: Optional[Path], kind: str, origin: str,
        generated: Optional[bool], created_at: object = None,
        metadata: Optional[dict] = None, object_type: Optional[str] = None,
        object_id: Optional[str] = None, conversation_id: Optional[str] = None,
        message_id: Optional[str] = None, project_id: Optional[str] = None,
        role: Optional[str] = None, ordinal: Optional[int] = None,
    ) -> None:
        available = bool(path and path.is_file())
        current = self._assets_by_id.get(asset_id)
        if current is None:
            current = Asset(
                asset_id=asset_id, source=self.source_name, account_id=self.account_id,
                asset_kind=kind, asset_origin=origin,
                file_name=path.name if available else None,
                mime_type=self._mime_type(path) if available and path else None,
                size_bytes=path.stat().st_size if available and path else None,
                asset_path=self._data_relative_asset_path(path) if available and path else None,
                is_model_generated=generated, is_preserved_missing=not available,
                is_binary_available=available,
                created_at=self._ts(created_at) if created_at is not None else None,
                metadata_json=(json.dumps(metadata, ensure_ascii=False, sort_keys=True)
                               if metadata else None),
            )
            self._assets_by_id[asset_id] = current
            self.assets.append(current)
        elif available and not current.is_binary_available and path:
            current.file_name = path.name
            current.mime_type = self._mime_type(path)
            current.size_bytes = path.stat().st_size
            current.asset_path = self._data_relative_asset_path(path)
            current.is_binary_available = True
            current.is_preserved_missing = False

        if not (object_type and object_id and role):
            return
        link_id = make_asset_link_id(
            self.source_name, self.account_id, asset_id, object_type, object_id,
            role, ordinal, None,
        )
        if link_id in self._asset_link_ids:
            return
        self.asset_links.append(AssetLink(
            asset_link_id=link_id, source=self.source_name, account_id=self.account_id,
            asset_id=asset_id, object_type=object_type, object_id=object_id,
            conversation_id=conversation_id, message_id=message_id,
            project_id=project_id, role=role, ordinal=ordinal,
            content_block_index=None, metadata_json=None,
        ))
        self._asset_link_ids.add(link_id)

    def _attach_message_path(self, message_id: str, path: Path) -> None:
        value = self._data_relative_asset_path(path)
        for message in self.messages:
            if message.message_id != message_id:
                continue
            paths = list(message.asset_paths or [])
            if value not in paths:
                paths.append(value)
                message.asset_paths = paths
            return

    def _record_preserved_file_assets(self) -> None:
        """Index files materialized beside the raw conversation envelope."""
        for index_path in sorted(self.raw_root.glob("project_sources/*/_files.json")):
            project_id = index_path.parent.name
            try:
                records = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(records, list):
                continue
            for ordinal, record in enumerate(records):
                if not isinstance(record, dict) or not record.get("file_id"):
                    continue
                candidate = index_path.parent / str(record.get("name") or "")
                path = candidate if candidate.is_file() else None
                self._add_preserved_asset(
                    asset_id=str(record["file_id"]), path=path, kind="project_file",
                    origin="user", generated=False,
                    created_at=record.get("created_at"),
                    metadata={"representation": "project_source"},
                    object_type="project", object_id=project_id,
                    project_id=project_id, role="context", ordinal=ordinal,
                )

        for representation, folder, id_key, prefix in (
            ("canvas", "canvases", "textdoc_id", "canvas"),
            ("deep_research_report", "deep_research", "async_task_id", "deep-research"),
        ):
            meta_paths = sorted((self.assets_root / folder).glob("*/*.meta.json"))
            reconstructed_canvas_messages: set[str] = set()
            if representation == "canvas":
                for candidate in meta_paths:
                    try:
                        candidate_meta = json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if (candidate_meta.get("materialization") == "canvas_replay_v1"
                            and candidate_meta.get("message_id")):
                        reconstructed_canvas_messages.add(str(candidate_meta["message_id"]))
            for meta_path in meta_paths:
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                message_id = meta.get("message_id")
                if (representation == "canvas"
                        and meta.get("materialization") != "canvas_replay_v1"
                        and str(message_id) in reconstructed_canvas_messages):
                    continue
                native_id = meta.get(id_key)
                conv_id = meta.get("conv_id") or meta_path.parent.name
                if not native_id or (representation == "canvas" and native_id == "unknown"):
                    native_id = message_id if representation == "canvas" else native_id
                if not native_id:
                    continue
                path = Path(str(meta_path)[:-len(".meta.json")])
                if representation == "canvas":
                    version = meta.get("version")
                    if version is None:
                        continue
                    asset_id = str(meta.get("asset_id") or f"{prefix}:{native_id}:v{version}")
                    kind = "artifact"
                else:
                    asset_id = f"{prefix}:{native_id}"
                    kind = "output"
                valid_message = bool(message_id and any(m.message_id == message_id for m in self.messages))
                self._add_preserved_asset(
                    asset_id=asset_id, path=path if path.is_file() else None,
                    kind=kind, origin="assistant", generated=True,
                    created_at=meta.get("create_time"),
                    metadata={
                        "representation": representation,
                        "materialization": meta.get("materialization"),
                        "native_textdoc_id": meta.get("native_textdoc_id"),
                        "response_message_id": meta.get("response_message_id"),
                        "replay_evidence": meta.get("evidence"),
                        "version": meta.get("version"),
                    },
                    object_type="message" if valid_message else ("conversation" if conv_id else None),
                    object_id=message_id if valid_message else conv_id,
                    conversation_id=conv_id, message_id=message_id if valid_message else None,
                    role="output", ordinal=0,
                )
                if valid_message and path.is_file():
                    self._attach_message_path(message_id, path)

        known_conversations = {c.conversation_id for c in self.conversations}
        for folder, representation in (("images", "orphan_image"),
                                       ("images_from_zip", "export_image")):
            for path in sorted((self.assets_root / folder).glob("*/*")):
                if not path.is_file() or path.name.endswith((".meta.json", "_meta.json")):
                    continue
                conv_id = path.parent.name
                if folder == "images":
                    asset_id = path.name.split("__", 1)[0]
                    if asset_id in self._assets_by_id:
                        continue
                else:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    locator = f"{conv_id}\x1f{path.name}"
                    asset_id = f"export-image:{hashlib.sha256(locator.encode()).hexdigest()}"
                has_conversation = conv_id in known_conversations
                self._add_preserved_asset(
                    asset_id=asset_id, path=path, kind="other", origin="unknown",
                    generated=None, metadata={
                        "content_sha256": digest if folder == "images_from_zip" else None,
                        "representation": representation,
                    },
                    object_type="conversation" if has_conversation else None,
                    object_id=conv_id if has_conversation else None,
                    conversation_id=conv_id if has_conversation else None,
                    role="unknown" if has_conversation else None,
                )

    def _repair_asset_link_targets(
        self, conv_id: str, mapping: dict, canonical_message_ids: set[str], start: int,
    ) -> None:
        """Resolve links only to retained messages, otherwise degrade placement."""
        node_by_message_id = {
            (node.get("message") or {}).get("id"): node
            for node in mapping.values()
            if (node.get("message") or {}).get("id")
        }
        rebuilt_ids = {link.asset_link_id for link in self.asset_links[:start]}
        repaired: list[AssetLink] = []
        for link in self.asset_links[start:]:
            metadata = json.loads(link.metadata_json) if link.metadata_json else {}
            native_tool_id = metadata.get("native_tool_message_id")
            if not native_tool_id:
                if link.message_id not in canonical_message_ids:
                    link.object_type = "conversation"
                    link.object_id = conv_id
                    link.message_id = None
                    link.content_block_index = None
                    link.asset_link_id = make_asset_link_id(
                        self.source_name, self.account_id, link.asset_id,
                        "conversation", conv_id, link.role, link.ordinal, None,
                    )
                if link.asset_link_id not in rebuilt_ids:
                    repaired.append(link)
                rebuilt_ids.add(link.asset_link_id)
                continue
            node = node_by_message_id.get(native_tool_id)
            candidate = node.get("parent") if node else None
            visited: set[str] = set()
            while candidate and candidate not in canonical_message_ids and candidate not in visited:
                visited.add(candidate)
                parent_node = mapping.get(candidate) or node_by_message_id.get(candidate)
                candidate = parent_node.get("parent") if parent_node else None
            if candidate in canonical_message_ids:
                link.object_id = candidate
                link.message_id = candidate
            else:
                link.object_type = "conversation"
                link.object_id = conv_id
                link.message_id = None
            link.asset_link_id = make_asset_link_id(
                self.source_name, self.account_id, link.asset_id, link.object_type,
                link.object_id, link.role, link.ordinal, link.content_block_index,
            )
            if link.asset_link_id not in rebuilt_ids:
                repaired.append(link)
                rebuilt_ids.add(link.asset_link_id)
        self.asset_links[start:] = repaired
        self._asset_link_ids = rebuilt_ids

    def _record_image_assets(
        self, *, msg: dict, conv_id: str, canonical_message_id: str, role: str,
    ) -> None:
        """Index native image pointers without publishing their upstream URLs."""
        parts = (msg.get("content") or {}).get("parts") or []
        asset_ordinal = 0
        for block_index, part in enumerate(parts):
            if not isinstance(part, dict) or part.get("content_type") != "image_asset_pointer":
                continue
            pointer = part.get("asset_pointer") or ""
            asset_id = parse_asset_pointer(pointer)
            if not asset_id:
                continue
            is_dalle = bool((part.get("metadata") or {}).get("dalle"))
            if role == "user":
                origin, kind, generated, link_role = "user", "attachment", False, "input"
            else:
                origin = "assistant"
                kind = "generated" if is_dalle else "output"
                generated, link_role = True, "output"

            resolved_value = resolve_asset_path(pointer, conv_id, self.assets_root)
            resolved = Path(resolved_value) if resolved_value else None
            available = bool(resolved and resolved.is_file())
            metadata_json = json.dumps({
                "height": part.get("height"),
                "pointer_scheme": pointer.split("://", 1)[0] if "://" in pointer else None,
                "representation": "image_asset_pointer",
                "width": part.get("width"),
            }, ensure_ascii=False, sort_keys=True)
            current = self._assets_by_id.get(asset_id)
            if current is None:
                current = Asset(
                    asset_id=asset_id, source=self.source_name, account_id=self.account_id,
                    asset_kind=kind, asset_origin=origin,
                    file_name=resolved.name if available else None,
                    mime_type=mimetypes.guess_type(resolved.name)[0] if available else part.get("mime_type"),
                    size_bytes=(resolved.stat().st_size if available else part.get("size_bytes")),
                    asset_path=self._data_relative_asset_path(resolved) if available else None,
                    is_model_generated=generated, is_preserved_missing=False,
                    is_binary_available=available, created_at=None, metadata_json=metadata_json,
                )
                self._assets_by_id[asset_id] = current
                self.assets.append(current)
            else:
                if current.asset_origin != origin:
                    current.asset_origin = "unknown"
                    current.asset_kind = "other"
                    current.is_model_generated = None
                if available and not current.is_binary_available:
                    current.file_name = resolved.name
                    current.mime_type = mimetypes.guess_type(resolved.name)[0]
                    current.size_bytes = resolved.stat().st_size
                    current.asset_path = self._data_relative_asset_path(resolved)
                    current.is_binary_available = True

            link_id = make_asset_link_id(
                self.source_name, self.account_id, asset_id, "message",
                canonical_message_id, link_role, asset_ordinal, block_index,
            )
            if canonical_message_id and link_id not in self._asset_link_ids:
                link_metadata = None
                if role == "tool":
                    link_metadata = json.dumps(
                        {
                            "native_content_block_index": block_index,
                            "native_tool_message_id": msg.get("id"),
                        }, sort_keys=True,
                    )
                self.asset_links.append(AssetLink(
                    asset_link_id=link_id, source=self.source_name, account_id=self.account_id,
                    asset_id=asset_id, object_type="message", object_id=canonical_message_id,
                    conversation_id=conv_id, message_id=canonical_message_id, project_id=None,
                    role=link_role, ordinal=asset_ordinal,
                    content_block_index=(None if role == "tool" else block_index),
                    metadata_json=link_metadata,
                ))
                self._asset_link_ids.add(link_id)
            asset_ordinal += 1

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
            account_id=self.account_id,
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
            account_id=self.account_id,
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
            account_id=self.account_id,
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
            account_id=self.account_id,
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
        """Override de BaseParser.save — paths source-prefixed (alinha com
        claude_ai/qwen/deepseek/gemini/perplexity).

        Layout:
            <output_dir>/chatgpt_conversations.parquet
            <output_dir>/chatgpt_messages.parquet
            <output_dir>/chatgpt_tool_events.parquet
            <output_dir>/chatgpt_branches.parquet
            <output_dir>/chatgpt_assets.parquet
            <output_dir>/chatgpt_asset_links.parquet
            <output_dir>/chatgpt_agent_memories.parquet
            <output_dir>/chatgpt_agent_memory_versions.parquet
            <output_dir>/chatgpt_agent_memory_temporal_evidence.parquet
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        conv_df = conversations_to_df(self.conversations)
        if not conv_df.empty:
            conv_df.to_parquet(output_dir / "chatgpt_conversations.parquet", index=False)

        msg_df = messages_to_df(self.messages)
        if not msg_df.empty:
            msg_df["word_count"] = msg_df["content"].fillna("").str.split().str.len()
            msg_df.to_parquet(output_dir / "chatgpt_messages.parquet", index=False)

        evt_df = tool_events_to_df(self.events)
        if not evt_df.empty:
            evt_df.to_parquet(output_dir / "chatgpt_tool_events.parquet", index=False)

        br_df = self.branches_df()
        if not br_df.empty:
            br_df.to_parquet(output_dir / "chatgpt_branches.parquet", index=False)

        assets_to_df(self.assets).to_parquet(output_dir / "chatgpt_assets.parquet", index=False)
        asset_links_to_df(self.asset_links).to_parquet(
            output_dir / "chatgpt_asset_links.parquet", index=False,
        )
        for name, items, convert in (
            ("agent_memories", self.agent_memories, agent_memories_to_df),
            ("agent_memory_versions", self.agent_memory_versions, agent_memory_versions_to_df),
            ("agent_memory_temporal_evidence", self.agent_memory_temporal_evidence, agent_memory_temporal_evidence_to_df),
        ):
            convert(items).to_parquet(output_dir / f"chatgpt_{name}.parquet", index=False)
