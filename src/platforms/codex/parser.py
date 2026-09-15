"""Parser canonico v3 do Codex CLI.

Le sessoes JSONL de `data/raw/Codex/<year>/<month>/<day>/rollout-*.jsonl`.

Schema empirico:
- Eventos sequenciais: session_meta, turn_context, event_msg, response_item
- `session_meta`: id (= conversation_id), cwd, model_provider
- `turn_context`: model
- `event_msg.user_message` / `agent_message`: conteudo de chat
- `event_msg.agent_reasoning`: thinking (acumulado e attached a proxima agent_message)
- `event_msg.exec_command_end`: enriquece tool event com duration_ms + success
- `response_item.function_call`: tool_use, correlacionado com exec_command_end via call_id

Output: data/processed/Codex/{codex_conversations,messages,tool_events,branches,
agent_memories,assets,asset_links}.parquet.

Branches: 1 _main por Conversation (Codex nao tem fork).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsing.agent_memory import parse_memories_for_source
from src.parsing.base import BaseParser
from src.schema.models import (
    AgentMemory,
    Asset,
    AssetLink,
    Branch,
    Conversation,
    Message,
    ToolEvent,
    agent_memories_to_df,
    asset_links_to_df,
    assets_to_df,
    branches_to_df,
    conversations_to_df,
    messages_to_df,
    make_asset_link_id,
    tool_events_to_df,
)


logger = logging.getLogger(__name__)


def make_input_image_asset_id(
    session_id: str,
    message_id: str,
    content_block_index: int,
    content_sha256: str,
) -> str:
    locator = "\x1f".join((session_id, message_id, str(content_block_index), content_sha256))
    return hashlib.sha256(locator.encode("utf-8")).hexdigest()


class CodexParser(BaseParser):
    source_name = "codex"

    def __init__(self, account: Optional[str] = None):
        super().__init__(account=account)
        self.branches: list[Branch] = []
        self.agent_memories: list[AgentMemory] = []
        self._conv_source_files: dict[str, set[str]] = {}
        self._input_path: Optional[Path] = None

    def reset(self):
        super().reset()
        self.branches = []
        self.agent_memories = []
        self._conv_source_files = {}
        self._input_path = None
        self.files_seen = 0
        self.files_parsed = 0
        self.files_skipped = 0
        self.assets: list[Asset] = []
        self.asset_links: list[AssetLink] = []

    def _materialize_input_image(
        self,
        data_uri: str,
        session_id: str,
        message_id: str,
        sequence: int,
        image_ordinal: int,
        content_block_index: int,
        created_at: pd.Timestamp,
    ) -> str:
        header, encoded = data_uri.split(",", 1)
        if not header.startswith("data:") or ";base64" not in header:
            raise ValueError("Codex input_image must use a base64 data URI")
        mime_type = header[5:].split(";", 1)[0] or "application/octet-stream"
        decoded = base64.b64decode(encoded, validate=True)
        digest = hashlib.sha256(decoded).hexdigest()
        extension = {
            "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(mime_type, ".bin")
        if self._input_path is None:
            raise ValueError("Codex input root is required to materialize images")
        out = self._input_path / "_images" / session_id / f"{sequence}_{image_ordinal}{extension}"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            if hashlib.sha256(out.read_bytes()).hexdigest() != digest:
                raise ValueError(f"preserved Codex image hash mismatch: {out}")
        else:
            out.write_bytes(decoded)
        asset_path = f"raw/Codex/_images/{session_id}/{out.name}"
        asset_id = make_input_image_asset_id(
            session_id, message_id, content_block_index, digest
        )
        self.assets.append(Asset(
            asset_id=asset_id, source=self.source_name, account_id=self.account_id,
            asset_kind="attachment", asset_origin="user", file_name=out.name,
            mime_type=mime_type, size_bytes=len(decoded), asset_path=asset_path,
            is_model_generated=False, is_preserved_missing=False,
            is_binary_available=True, created_at=created_at,
            metadata_json=json.dumps({"content_sha256": digest}, sort_keys=True),
        ))
        self.asset_links.append(AssetLink(
            asset_link_id=make_asset_link_id(
                self.source_name, self.account_id, asset_id, "message", message_id,
                "input", image_ordinal, content_block_index,
            ),
            source=self.source_name, account_id=self.account_id, asset_id=asset_id,
            object_type="message", object_id=message_id,
            conversation_id=session_id, message_id=message_id, project_id=None,
            role="input", ordinal=image_ordinal,
            content_block_index=content_block_index, metadata_json=None,
        ))
        return asset_path

    def parse(self, input_path: Path, home_memory_files: Optional[set[str]] = None) -> None:
        """Le todas sessoes em year/month/day/rollout-*.jsonl + memorias globais.

        Args:
            input_path: raw root, ex: data/raw/Codex/
            home_memory_files: paths relativos atuais no HOME do CLI (`memories/<file>.md`).
                Memorias em raw nao presentes nesse set viram is_preserved_missing=True.
                None ou set vazio marca todas as memorias como preserved.
        """
        input_path = Path(input_path)
        self._input_path = input_path
        for session_file in sorted(input_path.rglob("rollout-*.jsonl")):
            self.files_seen += 1
            if self._parse_session(session_file):
                self.files_parsed += 1
            else:
                self.files_skipped += 1
        self._build_branches()
        from src.capture.cli.preservation import mark_cli_preservation
        mark_cli_preservation(self)

        # Agent memory ingestion (Slice D — Task D1)
        mem_files = home_memory_files if home_memory_files is not None else set()
        self.agent_memories = parse_memories_for_source(input_path, "codex", mem_files)

    def parse_files(self, files: list[Path]) -> None:
        """Processa apenas a lista de arquivos especificada (uso incremental)."""
        for session_file in files:
            self.files_seen += 1
            if self._parse_session(session_file):
                self.files_parsed += 1
            else:
                self.files_skipped += 1
        self._build_branches()

    def _build_branches(self) -> None:
        """Gera 1 Branch <conv>_main por Conversation."""
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

    @staticmethod
    def _response_message_text(payload: dict) -> str:
        """Concatena apenas as partes textuais de `response_item.message`."""
        content = payload.get("content") or []
        if isinstance(content, str):
            return content
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") not in {"input_text", "output_text", "text"}:
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        return "\n\n".join(parts)

    def _parse_session(self, session_file: Path) -> bool:
        try:
            text = session_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"  {session_file}: falha ao ler: {e}")
            return False
        events = []
        for line in text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        meta = None
        model = None
        user_msgs = []
        agent_msgs = []
        response_msgs = []
        reasoning_parts: list[str] = []
        function_calls: dict[str, dict] = {}
        exec_ends: dict[str, dict] = {}
        timestamps = []

        adjacent_legacy_images: dict[int, list[tuple[int, str]]] = {}
        for index, evt in enumerate(events[:-1]):
            payload = evt.get("payload", {}) or {}
            next_payload = events[index + 1].get("payload", {}) or {}
            if (
                evt.get("type") == "response_item"
                and payload.get("type") == "message"
                and payload.get("role") == "user"
                and events[index + 1].get("type") == "event_msg"
                and next_payload.get("type") == "user_message"
            ):
                adjacent_legacy_images[index + 1] = [
                    (block_index, item["image_url"])
                    for block_index, item in enumerate(payload.get("content") or [])
                    if isinstance(item, dict)
                    and item.get("type") == "input_image"
                    and isinstance(item.get("image_url"), str)
                    and item["image_url"].startswith("data:")
                ]

        for event_index, evt in enumerate(events):
            ts = evt.get("timestamp")
            if ts:
                timestamps.append(ts)
            etype = evt.get("type")
            payload = evt.get("payload", {}) or {}

            if etype == "session_meta":
                # O primeiro meta identifica o rollout (e coincide com o ID
                # no filename). Alguns rollouts atuais incorporam historico
                # com um segundo session_meta de uma sessao anterior.
                meta = meta or payload
            elif etype == "turn_context":
                model = model or payload.get("model")
            elif etype == "event_msg":
                ptype = payload.get("type")
                if ptype == "user_message":
                    # Flush pending reasoning to previous agent msg
                    if agent_msgs and reasoning_parts:
                        agent_msgs[-1]["_thinking"] = "\n\n".join(reasoning_parts)
                        reasoning_parts = []
                    user_msgs.append({
                        "content": payload.get("message", ""), "ts": ts,
                        "_images": adjacent_legacy_images.get(event_index, []),
                    })
                elif ptype == "agent_message":
                    # Attach accumulated reasoning
                    thinking = "\n\n".join(reasoning_parts) if reasoning_parts else None
                    reasoning_parts = []
                    agent_msgs.append({
                        "content": payload.get("message", ""),
                        "ts": ts,
                        "_thinking": thinking,
                    })
                elif ptype == "agent_reasoning":
                    reasoning_parts.append(payload.get("text", ""))
                elif ptype == "exec_command_end":
                    call_id = payload.get("call_id")
                    if call_id:
                        exec_ends[call_id] = payload
            elif etype == "response_item":
                ptype = payload.get("type")
                if ptype == "message" and payload.get("role") in {"user", "assistant"}:
                    response_msgs.append({
                        "role": payload["role"],
                        "content": self._response_message_text(payload),
                        "ts": ts,
                        "_images": [
                            (block_index, item["image_url"])
                            for block_index, item in enumerate(payload.get("content") or [])
                            if isinstance(item, dict)
                            and item.get("type") == "input_image"
                            and isinstance(item.get("image_url"), str)
                            and item["image_url"].startswith("data:")
                        ],
                    })
                elif ptype == "function_call":
                    call_id = payload.get("call_id")
                    if call_id:
                        function_calls[call_id] = {"payload": payload, "ts": ts}

        # Flush trailing reasoning
        if agent_msgs and reasoning_parts:
            agent_msgs[-1]["_thinking"] = "\n\n".join(reasoning_parts)

        # Rollouts antigos duplicam mensagens em response_item; os eventos
        # legados continuam autoritativos quando presentes. Rollouts atuais
        # (observados desde 2026-08-13) usam somente response_item.message.
        if not user_msgs and not agent_msgs:
            for msg in response_msgs:
                if msg["role"] == "user":
                    user_msgs.append({
                        "content": msg["content"], "ts": msg["ts"],
                        "_images": msg.get("_images", []),
                    })
                else:
                    agent_msgs.append({
                        "content": msg["content"],
                        "ts": msg["ts"],
                        "_thinking": None,
                    })

        if not meta or (not user_msgs and not agent_msgs):
            return False

        session_id = meta["id"]
        cwd = meta.get("cwd", "")

        # Registra rel path pra preservation tracking (cli-copy preserva
        # arquivos quando user apaga do source HOME)
        if self._input_path is not None:
            try:
                rel = str(session_file.relative_to(self._input_path))
                self._conv_source_files.setdefault(session_id, set()).add(rel)
            except ValueError:
                pass  # session_file nao eh subpath de input_path

        # Build messages interleaved by timestamp
        all_msgs = []
        for m in user_msgs:
            all_msgs.append({"role": "user", **m})
        for m in agent_msgs:
            all_msgs.append({"role": "assistant", **m})
        all_msgs.sort(key=lambda m: m["ts"] or "")

        messages = []
        for seq, m in enumerate(all_msgs, 1):
            ct_parts = ["text"]
            if m.get("_thinking"):
                ct_parts.insert(0, "thinking")

            message_id = f"{session_id}_{seq}"
            created_at = self._ts(m["ts"])
            asset_paths = [
                self._materialize_input_image(
                    data_uri, session_id, message_id, seq, image_ordinal,
                    content_block_index, created_at,
                )
                for image_ordinal, (content_block_index, data_uri)
                in enumerate(m.get("_images", []))
            ]
            content_types = ct_parts + (["image"] if asset_paths else [])
            messages.append(Message(
                message_id=message_id,
                conversation_id=session_id,
                source=self.source_name,
                sequence=seq,
                role=m["role"],
                content=m["content"],
                model=model if m["role"] == "assistant" else None,
                created_at=created_at,
                account=self.account,
                thinking=m.get("_thinking"),
                content_types=",".join(content_types),
                asset_paths=asset_paths or None,
                account_id=self.account_id,
            ))

        # Tool events (function_call enriquecido com exec_command_end)
        tool_events = []
        for call_id, fc in function_calls.items():
            payload = fc["payload"]
            args_str = payload.get("arguments", "{}")
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                args = {}

            exec_end = exec_ends.get(call_id)
            duration_ms = None
            success = None
            command = args.get("cmd")

            if exec_end:
                dur = exec_end.get("duration", {}) or {}
                duration_ms = dur.get("secs", 0) * 1000 + dur.get("nanos", 0) // 1_000_000
                success = exec_end.get("exit_code") == 0
                command = command or exec_end.get("command")

            tool_events.append(ToolEvent(
                event_id=call_id,
                conversation_id=session_id,
                message_id=f"{session_id}_tool_{call_id}",
                source=self.source_name,
                event_type="tool_call",
                tool_name=payload.get("name", ""),
                file_path=args.get("file_path"),
                command=command,
                duration_ms=duration_ms,
                success=success,
            ))

        self.conversations.append(Conversation(
            conversation_id=session_id,
            source=self.source_name,
            title=None,
            created_at=self._ts(timestamps[0]) if timestamps else None,
            updated_at=self._ts(timestamps[-1]) if timestamps else None,
            message_count=len(messages),
            model=model,
            account=self.account,
            mode="cli",
            project=cwd,
        ))
        self.messages.extend(messages)
        self.events.extend(tool_events)
        return True

    def branches_df(self) -> pd.DataFrame:
        return branches_to_df(self.branches)

    def write_parquets(self, output_dir: Path) -> dict[str, int]:
        """Escreve 7 parquets canonicos. Idempotente."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        conversations_to_df(self.conversations).to_parquet(
            output_dir / "codex_conversations.parquet", index=False)
        messages_to_df(self.messages).to_parquet(
            output_dir / "codex_messages.parquet", index=False)
        tool_events_to_df(self.events).to_parquet(
            output_dir / "codex_tool_events.parquet", index=False)
        branches_to_df(self.branches).to_parquet(
            output_dir / "codex_branches.parquet", index=False)
        agent_memories_to_df(self.agent_memories).to_parquet(
            output_dir / "codex_agent_memories.parquet", index=False)
        assets_to_df(self.assets).to_parquet(
            output_dir / "codex_assets.parquet", index=False)
        asset_links_to_df(self.asset_links).to_parquet(
            output_dir / "codex_asset_links.parquet", index=False)
        return {
            "conversations": len(self.conversations),
            "messages": len(self.messages),
            "tool_events": len(self.events),
            "branches": len(self.branches),
            "agent_memories": len(self.agent_memories),
            "assets": len(self.assets),
            "asset_links": len(self.asset_links),
        }
