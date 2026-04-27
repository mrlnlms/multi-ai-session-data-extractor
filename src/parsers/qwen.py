"""Parser para dados exportados do Qwen."""

import json
import logging
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message

logger = logging.getLogger(__name__)


class QwenParser(BaseParser):
    source_name = "qwen"

    def parse(self, input_path: Path) -> None:
        with open(input_path, encoding="utf-8") as f:
            raw = json.load(f)

        conversations = raw.get("data", [])

        for conv_data in conversations:
            messages = self._extract_messages(conv_data)
            if not messages:
                continue

            model = self._extract_model(conv_data)

            self.conversations.append(Conversation(
                conversation_id=conv_data["id"],
                source=self.source_name,
                title=conv_data.get("title") or None,
                created_at=self._ts(conv_data["created_at"]),
                updated_at=self._ts(conv_data["updated_at"]),
                message_count=len(messages),
                model=model,
                account=self.account,
                mode="chat",
                url=f"https://chat.qwen.ai/c/{conv_data['id']}",
            ))
            self.messages.extend(messages)

    def _extract_messages(self, conv_data: dict) -> list[Message]:
        msg_dict = conv_data.get("chat", {}).get("history", {}).get("messages", {})
        if not msg_dict:
            return []

        conv_id = conv_data["id"]
        messages = []
        seq = 0

        roots = [mid for mid, mdata in msg_dict.items() if mdata.get("parentId") is None]
        if not roots:
            return []
        if len(roots) > 1:
            logger.warning(f"Conversa {conv_id}: {len(roots)} roots encontradas, usando primeira")
        root_id = roots[0]

        current_id = root_id
        while current_id:
            mdata = msg_dict.get(current_id)
            if mdata is None:
                break

            content, timestamp = self._extract_content(mdata)
            if content:
                seq += 1
                role = mdata.get("role", "user")
                files = mdata.get("files") or []
                file_names = [f["name"] for f in files if f.get("name")]
                has_files = len(file_names) > 0

                content_types = "text"
                if has_files:
                    content_types = "text,document"

                created_at = self._ts(timestamp) if timestamp else self._ts(conv_data["created_at"])

                messages.append(Message(
                    message_id=mdata["id"],
                    conversation_id=conv_id,
                    source=self.source_name,
                    sequence=seq,
                    role=role,
                    content=content,
                    model=mdata.get("model") if role == "assistant" else None,
                    created_at=created_at,
                    account=self.account,
                    content_types=content_types,
                    attachment_names=json.dumps(file_names) if has_files else None,
                ))

            children = mdata.get("childrenIds", [])
            current_id = children[-1] if children else None

        return messages

    def _extract_content(self, mdata: dict) -> tuple[str | None, int | None]:
        content_list = mdata.get("content_list", [])
        if content_list:
            text = content_list[0].get("content", "")
            ts = content_list[0].get("timestamp")
            return text if text else None, ts
        text = mdata.get("content", "")
        return text if text else None, None

    def _extract_model(self, conv_data: dict) -> str | None:
        msg_dict = conv_data.get("chat", {}).get("history", {}).get("messages", {})
        for mdata in msg_dict.values():
            if mdata.get("model"):
                return mdata["model"]
        return None
