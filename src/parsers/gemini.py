"""Parser para dados exportados do Gemini (enriched format)."""

import json
import logging
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message

logger = logging.getLogger(__name__)


class GeminiParser(BaseParser):
    source_name = "gemini"

    def _fix_tz(self, ts: str | None) -> str | None:
        """Conta pessoal do MyActivity exporta tz errado (+03:00) — horario em si
        e BRT, so o offset esta trocado. Correcao sistematica: substituir por -03:00.
        Ver docs/research/inventario-fontes.md (gemini timezone bug)."""
        if ts and self.account == "pessoal" and ts.endswith("+03:00"):
            return ts[:-6] + "-03:00"
        return ts

    def parse(self, input_path: Path) -> None:
        with open(input_path, encoding="utf-8") as f:
            conversations = json.load(f)

        for conv_data in conversations:
            turns = conv_data.get("messages", [])
            if not turns:
                continue

            href_id = conv_data.get("href", "").split("/")[-1]
            if not href_id:
                href_id = f"unknown_{conv_data.get('index', 0)}"
            # Namespace por account pra evitar colisao entre contas
            conv_id = f"{self.account}_{href_id}" if self.account else href_id

            first_ts = self._fix_tz(conv_data.get("first_timestamp"))
            last_ts = self._fix_tz(conv_data.get("last_timestamp"))
            created_at = self._ts(first_ts) if first_ts else pd.NaT
            updated_at = self._ts(last_ts) if last_ts else created_at

            if pd.isna(created_at):
                logger.warning(f"Conversa {conv_id}: sem timestamps, propagando NaT para todas as msgs")

            messages = []
            seq = 0
            for turn in turns:
                turn_ts_str = self._fix_tz(turn.get("timestamp_iso"))
                turn_ts = self._ts(turn_ts_str) if turn_ts_str else created_at

                user_text = turn.get("user", "")
                model_text = turn.get("model", "")

                if user_text:
                    seq += 1
                    messages.append(Message(
                        message_id=f"{conv_id}_{turn['turn_id']}_user",
                        conversation_id=conv_id,
                        source=self.source_name,
                        sequence=seq,
                        role="user",
                        content=user_text,
                        model=None,
                        created_at=turn_ts,
                        account=self.account,
                        content_types="text",
                    ))

                if model_text:
                    seq += 1
                    messages.append(Message(
                        message_id=f"{conv_id}_{turn['turn_id']}_asst",
                        conversation_id=conv_id,
                        source=self.source_name,
                        sequence=seq,
                        role="assistant",
                        content=model_text,
                        model=None,
                        created_at=turn_ts,
                        account=self.account,
                        content_types="text",
                    ))

            url = conv_data.get("url") or f"https://gemini.google.com{conv_data.get('href', '')}"

            self.conversations.append(Conversation(
                conversation_id=conv_id,
                source=self.source_name,
                title=conv_data.get("title") or None,
                created_at=created_at,
                updated_at=updated_at,
                message_count=len(messages),
                model=None,
                account=self.account,
                mode="chat",
                url=url,
            ))
            self.messages.extend(messages)
