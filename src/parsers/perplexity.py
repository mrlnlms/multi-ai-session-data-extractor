"""Parser para dados exportados do Perplexity.

Limitacao: o export nao inclui timestamps por mensagem — todas as msgs
de um thread herdam last_query_datetime (timestamp da ultima query).
Analise temporal intra-thread nao e possivel.
"""

import json
import logging
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message, VALID_MODES

logger = logging.getLogger(__name__)


class PerplexityParser(BaseParser):
    source_name = "perplexity"

    def parse(self, input_path: Path) -> None:
        with open(input_path, encoding="utf-8") as f:
            threads = json.load(f)

        for thread in threads:
            msgs_data = thread.get("extracted_messages", [])
            if not msgs_data:
                continue

            thread_ts = self._ts(thread["last_query_datetime"])
            mode = thread.get("mode")
            if mode not in VALID_MODES:
                mode = "chat"

            messages = []
            for seq, msg in enumerate(msgs_data, start=1):
                messages.append(Message(
                    message_id=f"{thread['uuid']}_{seq}",
                    conversation_id=thread["uuid"],
                    source=self.source_name,
                    sequence=seq,
                    role=msg["role"],
                    content=msg["text"],
                    model=None,
                    created_at=thread_ts,
                    account=self.account,
                    content_types="text",
                ))

            slug = thread.get("slug") or thread["uuid"]
            self.conversations.append(Conversation(
                conversation_id=thread["uuid"],
                source=self.source_name,
                title=thread.get("title") or None,
                created_at=thread_ts,
                updated_at=thread_ts,
                message_count=len(messages),
                model=thread.get("display_model"),
                account=self.account,
                mode=mode,
                url=f"https://www.perplexity.ai/search/{slug}",
            ))
            self.messages.extend(messages)
