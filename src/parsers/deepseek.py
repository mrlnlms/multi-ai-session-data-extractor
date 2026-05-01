"""Parser canonico do DeepSeek — schema v3.

Consome merged em data/merged/DeepSeek/conversations/<uuid>.json (1 file por
session). Gera 4 parquets canonicos.

Cobertura (probe 2026-05-01):
- Branches via parent_id + current_message_id (DAG plano)
- thinking_content (R1 reasoning) → Message.thinking
- thinking_elapsed_secs preservado em settings/metadata
- search_results → ToolEvent (event_type=search_call/_result)
- accumulated_token_usage → Message.token_count
- pinned (✅ cross-platform) → Conversation.is_pinned
- agent (chat/agent) + model_type → Conversation.mode + settings_json
- incomplete_message + status → Message.finish_reason
- files per msg → Message.attachment_names
- feedback per msg preservado em settings_json (per-conv consolidado)

DeepSeek nao tem projects nem folders — schema mais simples que Qwen/Claude.ai.

Output: data/processed/DeepSeek/{conversations,messages,tool_events,branches}.parquet
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers._deepseek_helpers import (
    build_branches_deepseek,
    normalize_status_to_finish_reason,
)
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


SOURCE = "deepseek"
ROLE_MAP = {"USER": "user", "ASSISTANT": "assistant"}  # uppercase no DeepSeek


class DeepSeekParser(BaseParser):
    source_name = SOURCE

    def __init__(
        self,
        account: Optional[str] = None,
        merged_root: Optional[Path] = None,
    ):
        super().__init__(account)
        self.merged_root = Path(merged_root) if merged_root else Path("data/merged/DeepSeek")

    def reset(self):
        super().reset()
        self.branches: list[Branch] = []

    @property
    def conversations_dir(self) -> Path:
        return self.merged_root / "conversations"

    def parse(self, input_path: Path) -> None:
        input_path = Path(input_path)
        if input_path.is_dir():
            self._parse_merged_dir(input_path)
        elif input_path.is_file():
            with open(input_path, encoding="utf-8") as f:
                obj = json.load(f)
            self._parse_conv(obj, last_run_date=obj.get("_last_seen_in_server"))
        else:
            raise FileNotFoundError(f"Input nao existe: {input_path}")

    def _parse_merged_dir(self, merged_root: Path) -> None:
        self.merged_root = merged_root
        conv_dir = merged_root / "conversations"
        last_run_date = self._compute_last_run_date(conv_dir)

        if conv_dir.exists():
            for fp in sorted(conv_dir.glob("*.json")):
                try:
                    with open(fp, encoding="utf-8") as f:
                        obj = json.load(f)
                except Exception:
                    continue
                self._parse_conv(obj, last_run_date=last_run_date)

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

    def _parse_conv(self, raw: dict, last_run_date: Optional[str]) -> None:
        # raw eh o biz_data (que ja foi unpacked pelo extractor)
        # Schema: {chat_session: {...}, chat_messages: [...]}
        sess = raw.get("chat_session") or {}
        chat_messages = raw.get("chat_messages") or []
        conv_id = sess.get("id")
        if not conv_id:
            return

        # Branches
        current_msg_id = sess.get("current_message_id")
        msg_to_branch, branch_records = build_branches_deepseek(
            conv_id, chat_messages, current_msg_id
        )

        # Mode: agent (chat|agent) + model_type
        agent = sess.get("agent") or "chat"
        model_type = sess.get("model_type") or "default"
        if model_type == "thinking" or "reason" in (model_type or "").lower():
            mode = "research"
        elif agent == "agent":
            mode = "research"  # agent mode → research-like
        else:
            mode = "chat"

        # Build messages
        messages: list[Message] = []
        tool_events: list[ToolEvent] = []
        for seq, msg in enumerate(chat_messages, start=1):
            built = self._build_message(conv_id, sess, msg, seq, msg_to_branch)
            if built is not None:
                messages.append(built)
                tool_events.extend(self._extract_tool_events(conv_id, msg))

        # Branch records
        for br in branch_records:
            self.branches.append(Branch(
                branch_id=br["branch_id"],
                conversation_id=conv_id,
                source=SOURCE,
                root_message_id=br["root_message_id"],
                leaf_message_id=br["leaf_message_id"],
                is_active=br["is_active"],
                created_at=self._ts(br["created_at"]) if br["created_at"] else self._ts(sess.get("inserted_at")),
                parent_branch_id=br["parent_branch_id"],
            ))

        # Conversation
        last_seen = raw.get("_last_seen_in_server")
        is_preserved = bool(raw.get("_preserved_missing")) or (
            last_run_date is not None
            and last_seen is not None
            and last_seen < last_run_date
        )

        # Settings: agent + model_type + version + summary stats
        settings_blob = {
            "agent": agent,
            "model_type": model_type,
            "version": sess.get("version"),
            "title_type": sess.get("title_type"),
            "seq_id": sess.get("seq_id"),
            "is_empty": sess.get("is_empty"),
        }
        # Sumariza thinking_elapsed_secs total se houver
        thinking_total = sum(
            (m.get("thinking_elapsed_secs") or 0) for m in chat_messages
            if m.get("thinking_enabled") and m.get("thinking_elapsed_secs")
        )
        if thinking_total > 0:
            settings_blob["thinking_elapsed_total_secs"] = thinking_total
        # Sumariza accumulated_token_usage do leaf (ja eh cumulativo)
        if chat_messages:
            last_msg = chat_messages[-1]
            tu = last_msg.get("accumulated_token_usage")
            if tu:
                settings_blob["total_token_usage"] = tu
        settings_json = json.dumps(settings_blob, ensure_ascii=False)

        # Model: pega de qualquer msg que tenha
        model = None
        for m in chat_messages:
            if m.get("model"):
                model = m["model"]
                break

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=SOURCE,
            title=sess.get("title") or None,
            created_at=self._ts(sess.get("inserted_at")),
            updated_at=self._ts(sess.get("updated_at")),
            message_count=len(messages),
            model=model,
            account=self.account,
            mode=mode,
            url=f"https://chat.deepseek.com/a/chat/s/{conv_id}",
            project_id=None,  # DeepSeek nao tem projects
            is_pinned=bool(sess.get("pinned", False)),
            is_archived=False,  # DeepSeek nao expoe is_archived
            is_temporary=False,
            is_preserved_missing=is_preserved,
            last_seen_in_server=self._ts(last_seen) if last_seen else None,
            summary=None,  # DeepSeek nao tem summary auto-gerado
            settings_json=settings_json,
        ))

        self.messages.extend(messages)
        self.events.extend(tool_events)

    def _build_message(
        self,
        conv_id: str,
        sess: dict,
        msg: dict,
        seq: int,
        msg_to_branch: dict[str, str],
    ) -> Optional[Message]:
        role = ROLE_MAP.get(msg.get("role"))
        if role is None:
            return None

        msg_id_int = msg.get("message_id")
        if msg_id_int is None:
            return None
        msg_id = str(msg_id_int)

        content = msg.get("content") or ""
        # R1 reasoning chain
        thinking = msg.get("thinking_content") or None
        if thinking == "":
            thinking = None

        # Search results sao ToolEvent — citations json fica vazio aqui
        # Mas se quisermos preservar inline tambem, podemos incluir em citations_json

        files = msg.get("files") or []
        file_names = [f.get("name") or f.get("file_name") or "" for f in files if isinstance(f, dict)]
        file_names = [n for n in file_names if n]

        # block types
        block_types = ["text"] if content else []
        if thinking:
            block_types.append("thinking")
        if msg.get("search_enabled") and msg.get("search_results"):
            block_types.append("search")
        if file_names:
            block_types.append("file")

        # Token count
        token_count = msg.get("accumulated_token_usage")
        if token_count == 0:
            token_count = None

        # finish_reason
        finish_reason = normalize_status_to_finish_reason(
            msg.get("status"), msg.get("incomplete_message"),
        )

        # Citations JSON (search_results inline em msg, alem de gerar ToolEvent)
        citations = msg.get("search_results")
        citations_json = (
            json.dumps(citations, ensure_ascii=False)
            if citations and isinstance(citations, list)
            else None
        )

        model = msg.get("model") if role == "assistant" else None
        # Empty string como model? deixa None
        if model == "":
            model = None

        branch_id = msg_to_branch.get(msg_id, f"{conv_id}_main")

        # Latency (thinking_elapsed_secs eh especifico do thinking)
        # Block timestamps: usamos inserted_at como start; sem stop separado
        start_ts = msg.get("inserted_at")
        # Stop ts proxy: start + thinking_elapsed (se houver)
        stop_ts = None
        if start_ts and msg.get("thinking_elapsed_secs"):
            stop_ts = start_ts + msg["thinking_elapsed_secs"]

        return Message(
            message_id=msg_id,
            conversation_id=conv_id,
            source=SOURCE,
            sequence=seq,
            role=role,
            content=content,
            model=model,
            created_at=self._ts(start_ts) if start_ts else self._ts(sess.get("inserted_at")),
            account=self.account,
            token_count=token_count,
            attachment_names=json.dumps(file_names, ensure_ascii=False) if file_names else None,
            content_types=",".join(block_types) if block_types else "text",
            thinking=thinking,
            branch_id=branch_id,
            asset_paths=None,
            finish_reason=finish_reason,
            citations_json=citations_json,
            attachments_json=None,  # DeepSeek nao tem extracted_content
            start_timestamp=self._ts(start_ts) if start_ts else None,
            stop_timestamp=self._ts(stop_ts) if stop_ts else None,
        )

    def _extract_tool_events(self, conv_id: str, msg: dict) -> list[ToolEvent]:
        events: list[ToolEvent] = []
        msg_id = str(msg.get("message_id") or "")
        results = msg.get("search_results")

        if results and isinstance(results, list):
            events.append(ToolEvent(
                event_id=f"{msg_id}_search_call",
                conversation_id=conv_id,
                message_id=msg_id,
                source=SOURCE,
                event_type="search_call",
                tool_name="web_search",
                metadata_json=json.dumps({
                    "search_enabled": msg.get("search_enabled"),
                    "search_status": msg.get("search_status"),
                    "result_count": len(results),
                }, ensure_ascii=False),
            ))
            events.append(ToolEvent(
                event_id=f"{msg_id}_search_result",
                conversation_id=conv_id,
                message_id=msg_id,
                source=SOURCE,
                event_type="search_result",
                tool_name="web_search",
                success=True,
                result=json.dumps(results, ensure_ascii=False),
                metadata_json=json.dumps({
                    "search_status": msg.get("search_status"),
                }, ensure_ascii=False),
            ))

        return events

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

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
