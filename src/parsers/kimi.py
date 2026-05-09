"""Parser canonico do Kimi — schema v3.

Consome merged em data/merged/Kimi/conversations/<uuid>.json (envelope com
chat + messages) + skills.json + assets/.

Schema observado (probe 2026-05-09):
- chat: {id, name, files[], messageContent, lastRequest{options,tools,scenario}, createTime, updateTime}
- messages[]: {id, parentId, role, status, scenario?, blocks[], refs?, createTime, childrenMessageIds?}
  - role: 'user' | 'assistant' | 'system'
  - status: MESSAGE_STATUS_COMPLETED | MESSAGE_STATUS_UNSPECIFIED
  - scenario: ex SCENARIO_K2D5 (modo do K2.6)
  - blocks[]: {id, parentId, messageId, createTime, <kind>}  kind: text|tool|file
    - text.content
    - tool: {toolCallId, name, args, contents: [{searchResult: {id, base: {title,url,...}}}]}
    - file: TBD (probe pode revelar mais)
  - refs: {searchChunks[], usedSearchChunks[]}  (search results referenciados — duplicacao parcial de block.tool.contents)

Branches: parentId no message-level cria DAG; usamos build_branches_qwen
adaptado (mesma logica). leaf_messageId nao retornado mas pode-se inferir
pelo ultimo nao referenciado como parent.

Output: data/processed/Kimi/kimi_{conversations,messages,tool_events,
branches,project_metadata,assets}.parquet (project_metadata com 1 row
por skill instalada — analogo a Qwen project).
"""

from __future__ import annotations

import json
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


SOURCE = "kimi"

ROLE_MAP = {"user": "user", "assistant": "assistant", "system": "system"}


def _scenario_to_mode(scenario: Optional[str]) -> str:
    """Mapeia scenario do Kimi pra VALID_MODES.

    Scenarios observados: SCENARIO_K2D5 (default). Outros (slides/docs/sheets/
    deep_research) nao apareceram no smoke; ate confirmar mapeamento, todos
    caem em 'chat'.
    """
    if not scenario:
        return "chat"
    s = scenario.upper()
    if "RESEARCH" in s:
        return "research"
    if "SEARCH" in s:
        return "search"
    return "chat"


def _build_branches(
    conv_id: str,
    messages: list[dict],
) -> tuple[dict[str, str], list[dict]]:
    """Constroi branches a partir do DAG via parentId.

    Algoritmo simples (Kimi smoke nao mostrou forks claros):
    - Cada msg sem parent (parentId == "") = root de uma branch
    - Branch eh chain de msgs onde cada uma tem 1 child (depth-first)
    - Quando uma msg tem >1 child em childrenMessageIds, cria nova branch
      por filho

    Pra V1 simples: todas as msgs caem em <conv_id>_main (sem branches
    multiplas), ate observarmos forks empiricamente.
    """
    msg_to_branch: dict[str, str] = {}
    main_branch_id = f"{conv_id}_main"
    for m in messages:
        mid = m.get("id")
        if mid:
            msg_to_branch[mid] = main_branch_id
    # 1 branch por conv (V1)
    branch_records: list[dict] = []
    if messages:
        sorted_msgs = sorted(messages, key=lambda m: m.get("createTime") or "")
        root = sorted_msgs[0]
        leaf = sorted_msgs[-1]
        branch_records.append({
            "branch_id": main_branch_id,
            "root_message_id": root.get("id") or "",
            "leaf_message_id": leaf.get("id") or "",
            "is_active": True,
            "created_at": root.get("createTime"),
            "parent_branch_id": None,
        })
    return msg_to_branch, branch_records


class KimiParser(BaseParser):
    source_name = SOURCE

    def __init__(
        self,
        account: Optional[str] = None,
        merged_root: Optional[Path] = None,
    ):
        super().__init__(account)
        self.merged_root = Path(merged_root) if merged_root else Path("data/merged/Kimi")
        self.skills: dict = {"official": [], "installed": []}
        self.assets_manifest: dict = {}

    def reset(self):
        super().reset()
        self.branches: list[Branch] = []
        self.skills = {"official": [], "installed": []}
        self.assets_manifest = {}

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

        manifest_path = merged_root / "assets_manifest.json"
        if manifest_path.exists():
            try:
                self.assets_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) or {}
            except Exception:
                self.assets_manifest = {}

        conv_dir = merged_root / "conversations"
        if conv_dir.exists():
            for fp in sorted(conv_dir.glob("*.json")):
                try:
                    with open(fp, encoding="utf-8") as f:
                        envelope = json.load(f)
                except Exception:
                    continue
                self._parse_envelope(envelope)

        skills_path = merged_root / "skills.json"
        if skills_path.exists():
            try:
                self.skills = json.loads(skills_path.read_text(encoding="utf-8")) or {"official": [], "installed": []}
            except Exception:
                self.skills = {"official": [], "installed": []}

    def _parse_envelope(self, envelope: dict) -> None:
        chat = envelope.get("chat") or {}
        conv_id = chat.get("id")
        if not conv_id:
            return

        messages = envelope.get("messages") or []
        sorted_msgs = sorted(messages, key=lambda m: m.get("createTime") or "")

        msg_to_branch, branch_records = _build_branches(conv_id, messages)

        msgs: list[Message] = []
        events: list[ToolEvent] = []
        for seq, m in enumerate(sorted_msgs, start=1):
            built = self._build_message(conv_id, chat, m, seq, msg_to_branch)
            if built is not None:
                msgs.append(built)
                events.extend(self._extract_tool_events(conv_id, m))

        # Branch dataclass
        for br in branch_records:
            self.branches.append(Branch(
                branch_id=br["branch_id"],
                conversation_id=conv_id,
                source=SOURCE,
                root_message_id=br["root_message_id"],
                leaf_message_id=br["leaf_message_id"],
                is_active=br["is_active"],
                created_at=self._ts(br["created_at"]) if br["created_at"] else self._ts(chat.get("createTime")),
                parent_branch_id=br["parent_branch_id"],
            ))

        # Modelo: ultimo assistant que tenha info de model? Kimi nao expoe model
        # por message no smoke. Usa scenario como proxy ate confirmar.
        scenario = (chat.get("lastRequest") or {}).get("scenario") or ""
        model = scenario or None
        for m in reversed(sorted_msgs):
            if m.get("role") == "assistant" and m.get("scenario"):
                model = m["scenario"]
                break

        is_preserved = bool(envelope.get("_preserved_missing"))
        last_seen = envelope.get("_last_seen_in_server")

        # settings_json: lastRequest options + tools
        last_req = chat.get("lastRequest") or {}
        settings = {}
        if last_req:
            opts = last_req.get("options") or {}
            tools = last_req.get("tools") or []
            settings = {
                "scenario": last_req.get("scenario"),
                "options": opts,
                "tools": [t.get("type") for t in tools if isinstance(t, dict)],
            }
        settings_json = json.dumps(settings, ensure_ascii=False) if settings else None

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=SOURCE,
            title=chat.get("name") or None,
            created_at=self._ts(chat.get("createTime")),
            updated_at=self._ts(chat.get("updateTime")),
            message_count=len(msgs),
            model=model,
            account=self.account,
            mode=_scenario_to_mode(scenario),
            url=f"https://www.kimi.com/chat/{conv_id}",
            is_preserved_missing=is_preserved,
            last_seen_in_server=self._ts(last_seen) if last_seen else None,
            settings_json=settings_json,
        ))
        self.messages.extend(msgs)
        self.events.extend(events)

    def _build_message(
        self, conv_id: str, chat: dict, m: dict, seq: int,
        msg_to_branch: dict[str, str],
    ) -> Optional[Message]:
        role_raw = (m.get("role") or "").lower()
        role = ROLE_MAP.get(role_raw)
        if role is None:
            return None

        msg_id = m.get("id") or ""
        blocks = m.get("blocks") or []

        # Concatena content de blocks text
        text_parts: list[str] = []
        attachment_names: list[str] = []
        asset_paths: list[str] = []
        block_kinds: list[str] = []

        for b in blocks:
            if "text" in b:
                txt = (b.get("text") or {}).get("content") or ""
                if txt:
                    text_parts.append(txt)
                block_kinds.append("text")
            elif "tool" in b:
                block_kinds.append("tool")
            elif "file" in b:
                block_kinds.append("file")
                fobj = b.get("file") or {}
                fname = fobj.get("name") or fobj.get("id") or ""
                if fname:
                    attachment_names.append(fname)
                # Resolve asset_path via manifest
                fid = fobj.get("id")
                if fid and fid in self.assets_manifest:
                    rel = self.assets_manifest[fid].get("relpath")
                    if rel:
                        asset_paths.append(f"merged/Kimi/{rel}")

        # Resolve asset_paths via files inline na conversation tambem
        # (nem todo file vira block.file — chat.files[] eh authoritativo
        # pra files anexados a conv)
        if not asset_paths:
            for fobj in chat.get("files") or []:
                fid = fobj.get("id")
                if fid and fid in self.assets_manifest:
                    rel = self.assets_manifest[fid].get("relpath")
                    if rel:
                        asset_paths.append(f"merged/Kimi/{rel}")

        text_content = "\n\n".join(text_parts) if text_parts else ""

        # Status
        status = m.get("status") or ""
        finish_reason = None
        if status == "MESSAGE_STATUS_COMPLETED":
            finish_reason = None  # default sucesso
        elif status and status != "MESSAGE_STATUS_UNSPECIFIED":
            finish_reason = status.lower().replace("message_status_", "")

        # Model: usa scenario da msg se tiver
        model = m.get("scenario") if role == "assistant" else None

        branch_id = msg_to_branch.get(msg_id, f"{conv_id}_main")

        return Message(
            message_id=msg_id,
            conversation_id=conv_id,
            source=SOURCE,
            sequence=seq,
            role=role,
            content=text_content,
            model=model,
            created_at=self._ts(m.get("createTime")),
            account=self.account,
            attachment_names=json.dumps(attachment_names, ensure_ascii=False) if attachment_names else None,
            content_types=",".join(block_kinds) if block_kinds else "text",
            thinking=None,
            branch_id=branch_id,
            asset_paths=asset_paths or None,
            finish_reason=finish_reason,
        )

    def _extract_tool_events(self, conv_id: str, m: dict) -> list[ToolEvent]:
        events: list[ToolEvent] = []
        msg_id = m.get("id") or ""

        # 1) block.tool: 1 ToolEvent por block
        for b in m.get("blocks") or []:
            if "tool" not in b:
                continue
            t = b.get("tool") or {}
            tool_name = t.get("name") or "unknown"
            tool_call_id = t.get("toolCallId") or f"{msg_id}_{b.get('id','?')}"
            contents = t.get("contents") or []
            events.append(ToolEvent(
                event_id=f"{msg_id}_tool_{tool_call_id}",
                conversation_id=conv_id,
                message_id=msg_id,
                source=SOURCE,
                event_type=f"{tool_name}_call",
                tool_name=tool_name,
                command=t.get("args") or None,
                success=True,
                result=json.dumps(contents, ensure_ascii=False) if contents else None,
                metadata_json=json.dumps({
                    "toolCallId": tool_call_id,
                    "result_count": len(contents),
                }, ensure_ascii=False),
            ))

        # 2) refs.searchChunks / usedSearchChunks: emit pra contexto adicional
        # (nao duplicar quando ja temos block.tool com contents — block.tool
        # eh authoritativo; refs sao agregacao pra UI). Skip se block.tool ja
        # cobriu.
        has_tool_block = any("tool" in b for b in m.get("blocks") or [])
        if not has_tool_block:
            refs = m.get("refs") or {}
            if refs.get("usedSearchChunks"):
                events.append(ToolEvent(
                    event_id=f"{msg_id}_refs_search",
                    conversation_id=conv_id,
                    message_id=msg_id,
                    source=SOURCE,
                    event_type="search_result",
                    tool_name="web_search",
                    success=True,
                    result=json.dumps(refs["usedSearchChunks"], ensure_ascii=False),
                    metadata_json=json.dumps({"count": len(refs["usedSearchChunks"]), "kind": "usedSearchChunks"}, ensure_ascii=False),
                ))
        return events

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def assets_df(self) -> pd.DataFrame:
        if not self.assets_manifest:
            return pd.DataFrame(columns=[
                "asset_id", "chat_id", "name", "mime_type", "size_bytes",
                "asset_path", "url",
            ])
        rows = []
        for fid, info in self.assets_manifest.items():
            rows.append({
                "asset_id": fid,
                "chat_id": info.get("chat_id") or "",
                "name": info.get("name") or "",
                "mime_type": info.get("mime") or "",
                "size_bytes": int(info.get("size") or 0),
                "asset_path": f"merged/Kimi/{info['relpath']}" if info.get("relpath") else "",
                "url": info.get("url") or "",
            })
        return pd.DataFrame(rows)

    def project_metadata_df(self) -> pd.DataFrame:
        """1 row por skill instalada — Kimi skills funcionam como
        'projects' (modos especializados). Schema alinhado com Qwen
        project_metadata: project_id + name + custom_instruction +
        created_at + updated_at."""
        installed = self.skills.get("installed") or []
        if not installed:
            return pd.DataFrame(columns=[
                "project_id", "name", "icon", "custom_instruction",
                "is_pinned", "is_installed", "categories", "source_type",
                "created_at", "updated_at",
            ])
        rows = []
        for s in installed:
            rows.append({
                "project_id": s.get("id"),
                "name": s.get("name") or "",
                "icon": "",
                "custom_instruction": s.get("description") or "",
                "is_pinned": bool(s.get("pinned", False)),
                "is_installed": bool(s.get("installed", False)),
                "categories": ",".join(s.get("categories") or []),
                "source_type": s.get("source") or "",
                "created_at": pd.NaT,
                "updated_at": pd.NaT,
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

        as_df = self.assets_df()
        if not as_df.empty:
            as_df.to_parquet(output_dir / f"{self.source_name}_assets.parquet")
