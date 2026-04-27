"""Parser para dados exportados do ChatGPT (formato GPT2Claude Migration Kit)."""

import json
import zipfile
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message


class ChatGPTParser(BaseParser):
    source_name = "chatgpt"

    def parse(self, input_path: Path) -> None:
        with open(input_path, encoding="utf-8") as f:
            raw = json.load(f)

        conversations = raw.get("conversations", [])

        for conv_data in conversations:
            raw_messages = conv_data.get("messages", [])
            if not raw_messages:
                continue

            messages, has_research = self._extract_messages(conv_data["id"], raw_messages)
            mode = "research" if has_research else "chat"

            self.conversations.append(Conversation(
                conversation_id=conv_data["id"],
                source=self.source_name,
                title=conv_data.get("title") or None,
                created_at=self._ts(conv_data.get("create_time")),
                updated_at=self._ts(conv_data.get("update_time")),
                message_count=len(messages),
                model=conv_data.get("model"),
                account=self.account,
                mode=mode,
                project=conv_data.get("project") or None,
                url=f"https://chatgpt.com/c/{conv_data['id']}",
            ))
            self.messages.extend(messages)

    def _extract_messages(self, conv_id: str, raw_messages: list[dict]) -> tuple[list[Message], bool]:
        messages = []
        has_research = False
        pending_tool = None
        seq = 0

        for raw_msg in raw_messages:
            role = raw_msg.get("role", "")

            if role == "tool":
                pending_tool = raw_msg.get("content", "")
                if raw_msg.get("model") == "research":
                    has_research = True
                continue

            if role not in ("user", "assistant"):
                continue

            # Reset pending_tool se user msg vem antes de assistant consumir
            if role == "user" and pending_tool:
                pending_tool = None

            seq += 1
            tool_results = None
            if role == "assistant" and pending_tool:
                tool_results = pending_tool
                pending_tool = None

            created_at = self._ts(raw_msg.get("timestamp"))

            messages.append(Message(
                message_id=f"{conv_id}_{seq}",
                conversation_id=conv_id,
                source=self.source_name,
                sequence=seq,
                role=role,
                content=raw_msg.get("content", ""),
                model=raw_msg.get("model") if role == "assistant" else None,
                created_at=created_at,
                account=self.account,
                content_types="text",
                tool_results=tool_results,
            ))

        return messages, has_research

    def parse_dalle(self, dalle_zip_path: Path) -> None:
        """Extrai conversas e mensagens de geracoes DALL-E do export oficial."""
        with zipfile.ZipFile(dalle_zip_path) as z:
            names = z.namelist()

            # Ler captions (prompts) por generation_id
            captions = {}
            for n in names:
                if n.endswith("caption.txt") and "/generations/" in n:
                    gen_id = n.split("/generations/")[1].split("/")[0]
                    captions[gen_id] = z.read(n).decode("utf-8").strip()

            # In_conversation: agrupadas por conversation_id
            conv_images: dict[str, list[str]] = {}
            for n in names:
                if "/chatgptgenerations/" in n and "/conversations/" in n and not n.endswith("/"):
                    conv_id = n.split("/conversations/")[1].split("/")[0]
                    conv_images.setdefault(conv_id, []).append(n)

            # Verificar quais conversation_ids ja existem no dataset parseado
            existing_ids = {c.conversation_id for c in self.conversations}

            for conv_id, files in conv_images.items():
                if conv_id in existing_ids:
                    # Conversa ja existe — so marcar que tem DALL-E (via flag no futuro)
                    continue

                created_at = self._decode_hex_ts(conv_id)
                img_count = len(files)

                self.conversations.append(Conversation(
                    conversation_id=conv_id,
                    source=self.source_name,
                    title=f"[DALL-E, conversa perdida — {img_count} imagens]",
                    created_at=created_at,
                    updated_at=created_at,
                    message_count=1,
                    model="dall-e",
                    account=self.account,
                    mode="dalle",
                    url=f"https://chatgpt.com/c/{conv_id}",
                ))
                self.messages.append(Message(
                    message_id=f"{conv_id}_dalle_1",
                    conversation_id=conv_id,
                    source=self.source_name,
                    sequence=1,
                    role="assistant",
                    content=f"[{img_count} imagens geradas]",
                    model="dall-e",
                    created_at=created_at,
                    account=self.account,
                    content_types="image_generation",
                ))

            # Standalone: agrupar por prompt (dedup)
            seen_prompts: dict[str, list[str]] = {}
            for gen_id, prompt in captions.items():
                seen_prompts.setdefault(prompt, []).append(gen_id)

            for prompt, gen_ids in seen_prompts.items():
                total_images = len(gen_ids) * 2  # cada generation tem png + webp
                conv_id = f"dalle-standalone-{gen_ids[0]}"

                self.conversations.append(Conversation(
                    conversation_id=conv_id,
                    source=self.source_name,
                    title=f"[DALL-E Labs — {prompt[:50]}]",
                    created_at=pd.NaT,
                    updated_at=pd.NaT,
                    message_count=2,
                    model="dall-e",
                    account=self.account,
                    mode="dalle",
                ))
                self.messages.append(Message(
                    message_id=f"{conv_id}_1",
                    conversation_id=conv_id,
                    source=self.source_name,
                    sequence=1,
                    role="user",
                    content=prompt,
                    model=None,
                    created_at=pd.NaT,
                    account=self.account,
                    content_types="text",
                ))
                self.messages.append(Message(
                    message_id=f"{conv_id}_2",
                    conversation_id=conv_id,
                    source=self.source_name,
                    sequence=2,
                    role="assistant",
                    content=f"[{total_images} imagens geradas, {len(gen_ids)} variacoes]",
                    model="dall-e",
                    created_at=pd.NaT,
                    account=self.account,
                    content_types="image_generation",
                ))

    @staticmethod
    def _decode_hex_ts(conv_id: str) -> pd.Timestamp:
        """Tenta decodificar timestamp hex do prefixo do conversation_id."""
        hex_prefix = conv_id.split("-")[0]
        try:
            ts = int(hex_prefix, 16)
            dt = BaseParser._ts(ts)
            if 2020 <= dt.year <= 2026:
                return dt
        except (ValueError, OverflowError):
            pass
        return pd.NaT
