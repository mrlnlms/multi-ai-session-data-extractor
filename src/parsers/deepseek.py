"""Parser para dados exportados do DeepSeek."""

import json
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message


class DeepSeekParser(BaseParser):
    source_name = "deepseek"

    def parse(self, input_path: Path) -> None:
        with open(input_path, encoding="utf-8") as f:
            conversations = json.load(f)

        for conv_data in conversations:
            messages, has_search = self._extract_messages(conv_data)
            if not messages:
                continue

            model = self._extract_model(conv_data)
            mode = "search" if has_search else "chat"

            self.conversations.append(Conversation(
                conversation_id=conv_data["id"],
                source=self.source_name,
                title=conv_data.get("title") or None,
                created_at=self._ts(conv_data["inserted_at"]),
                updated_at=self._ts(conv_data["updated_at"]),
                message_count=len(messages),
                model=model,
                account=self.account,
                mode=mode,
                url=f"https://chat.deepseek.com/a/chat/s/{conv_data['id']}",
            ))
            self.messages.extend(messages)

    def _extract_messages(self, conv_data: dict) -> tuple[list[Message], bool]:
        """Percorre a tree de mapping extraindo mensagens do caminho principal."""
        mapping = conv_data["mapping"]
        conv_id = conv_data["id"]
        messages = []
        has_search = False
        seq = 0

        node_id = "root"
        while True:
            node = mapping.get(node_id)
            if node is None:
                break

            msg_data = node.get("message")
            if msg_data and msg_data.get("fragments"):
                parsed = self._parse_fragments(msg_data["fragments"])

                if parsed.get("search_content"):
                    has_search = True

                if parsed.get("user_content"):
                    seq += 1
                    messages.append(Message(
                        message_id=f"{conv_id}_{node_id}_user",
                        conversation_id=conv_id,
                        source=self.source_name,
                        sequence=seq,
                        role="user",
                        content=parsed["user_content"],
                        model=None,
                        created_at=self._ts(msg_data["inserted_at"]),
                        account=self.account,
                        content_types="text",
                    ))

                if parsed.get("assistant_content"):
                    seq += 1
                    messages.append(Message(
                        message_id=f"{conv_id}_{node_id}_asst",
                        conversation_id=conv_id,
                        source=self.source_name,
                        sequence=seq,
                        role="assistant",
                        content=parsed["assistant_content"],
                        model=msg_data.get("model"),
                        created_at=self._ts(msg_data["inserted_at"]),
                        account=self.account,
                        content_types="text",
                        thinking=parsed.get("thinking"),
                        tool_results=parsed.get("search_content"),
                    ))

            children = node.get("children", [])
            if not children:
                break
            node_id = children[-1]

        return messages, has_search

    def _parse_fragments(self, fragments: list[dict]) -> dict:
        """Agrupa fragments por tipo, concatenando duplicados."""
        parts = {"user": [], "assistant": [], "thinking": [], "search": []}
        for frag in fragments:
            ftype = frag.get("type", "")
            content = frag.get("content", "")
            if not content:
                continue
            if ftype == "REQUEST":
                parts["user"].append(content)
            elif ftype == "RESPONSE":
                parts["assistant"].append(content)
            elif ftype == "THINK":
                parts["thinking"].append(content)
            elif ftype in ("SEARCH", "READ_LINK"):
                parts["search"].append(content)
        result = {}
        if parts["user"]:
            result["user_content"] = "\n\n".join(parts["user"])
        if parts["assistant"]:
            result["assistant_content"] = "\n\n".join(parts["assistant"])
        if parts["thinking"]:
            result["thinking"] = "\n\n".join(parts["thinking"])
        if parts["search"]:
            result["search_content"] = "\n\n".join(parts["search"])
        return result

    def _extract_model(self, conv_data: dict) -> str | None:
        """Extrai modelo da primeira mensagem com model definido."""
        for node in conv_data["mapping"].values():
            msg = node.get("message")
            if msg and msg.get("model"):
                return msg["model"]
        return None
