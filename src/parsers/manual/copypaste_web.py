"""Parser pra conversas copiadas manualmente da web (plaintext).

Formato: arquivos .txt com conversas copiadas. Cada arquivo tem marcadores
diferentes dependendo da plataforma:
- GPT.txt: 'ChatGPT said:' separa resposta
- QWEEN.txt: 'Qwen3-Max\\n<H>:<M> AM/PM' separa respostas
- GEMINI-*.txt: 'Conversation with Gemini' header
- CLAUDE.txt, GEMINI-marlooon.txt: marcadores manuais '--- USER ---'/'--- ASSISTANT ---'

source = plataforma original (extraida do filename prefix)
capture_method = 'manual_copypaste'
"""

from __future__ import annotations

import logging
import os
import re
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import (
    Branch,
    Conversation,
    Message,
)


logger = logging.getLogger(__name__)


FILENAME_TO_SOURCE = {
    "CLAUDE": "claude_ai",
    "GPT": "chatgpt",
    "GEMINI": "gemini",
    "QWEEN": "qwen",
    "DEEPSEEK": "deepseek",
    "PERPLEXITY": "perplexity",
}


CAPTURE_METHOD = "manual_copypaste"


class CopypasteWebParser(BaseParser):
    source_name = "copypaste_web"

    def __init__(self, account: Optional[str] = None):
        super().__init__(account=account)
        self.branches: list[Branch] = []

    def reset(self):
        super().reset()
        self.branches = []

    def parse(self, input_path: Path) -> None:
        input_path = Path(input_path)
        for txt_file in sorted(input_path.glob("*.txt")):
            self._parse_file(txt_file)
        self._build_branches()

    def _build_branches(self) -> None:
        msgs_by_conv: dict[str, list[Message]] = {}
        for m in self.messages:
            msgs_by_conv.setdefault(m.conversation_id, []).append(m)
        for conv in self.conversations:
            msgs = sorted(msgs_by_conv.get(conv.conversation_id, []), key=lambda m: m.sequence)
            root_id = msgs[0].message_id if msgs else ""
            leaf_id = msgs[-1].message_id if msgs else ""
            self.branches.append(Branch(
                branch_id=f"{conv.conversation_id}_main",
                conversation_id=conv.conversation_id,
                source=conv.source,
                root_message_id=root_id,
                leaf_message_id=leaf_id,
                is_active=True,
                created_at=conv.created_at if conv.created_at is not None else pd.Timestamp.now(tz="UTC"),
            ))

    def _parse_file(self, file_path: Path) -> None:
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"  {file_path}: falha ao ler: {e}")
            return
        stem = file_path.stem
        source = self._detect_source(stem)
        conv_id = f"manual_copypaste_{stem.lower()}"
        file_ts = self._ts(os.path.getmtime(file_path))

        turns = self._parse_turns(text, stem)
        if not turns:
            logger.warning(f"  {file_path.name}: sem turnos detectados")
            return

        messages = []
        for seq, (role, content) in enumerate(turns, start=1):
            messages.append(Message(
                message_id=str(uuid_lib.uuid4()),
                conversation_id=conv_id,
                source=source,
                sequence=seq,
                role=role,
                content=content,
                model=None,
                created_at=file_ts,
                account=self.account,
                content_types="text",
            ))

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=source,
            title=stem,
            created_at=file_ts,
            updated_at=file_ts,
            message_count=len(messages),
            model=None,
            account=self.account,
            mode="chat",
            capture_method=CAPTURE_METHOD,
        ))
        self.messages.extend(messages)

    @staticmethod
    def _detect_source(stem: str) -> str:
        upper = stem.upper()
        for prefix, source in FILENAME_TO_SOURCE.items():
            if upper.startswith(prefix):
                return source
        return "chatgpt"  # fallback

    @staticmethod
    def _parse_turns(text: str, stem: str) -> list[tuple[str, str]]:
        upper = stem.upper()

        if "--- USER ---" in text or "--- ASSISTANT ---" in text:
            return CopypasteWebParser._parse_manual_markers(text)
        if upper.startswith("GPT"):
            return CopypasteWebParser._parse_gpt(text)
        if upper.startswith("QWEEN"):
            return CopypasteWebParser._parse_qwen(text)
        if upper.startswith("GEMINI"):
            return CopypasteWebParser._parse_gemini(text)
        return [("user", text.strip())]

    @staticmethod
    def _parse_manual_markers(text: str) -> list[tuple[str, str]]:
        parts = re.split(r"---\s*(USER|ASSISTANT)\s*---", text)
        turns = []
        i = 1
        while i < len(parts) - 1:
            marker = parts[i].strip().upper()
            content = parts[i + 1].strip()
            role = "user" if marker == "USER" else "assistant"
            if content:
                turns.append((role, content))
            i += 2
        return turns

    @staticmethod
    def _parse_gpt(text: str) -> list[tuple[str, str]]:
        parts = text.split("ChatGPT said:")
        turns = []
        if parts[0].strip():
            turns.append(("user", parts[0].strip()))
        for part in parts[1:]:
            content = part.strip()
            if content:
                turns.append(("assistant", content))
        return turns

    @staticmethod
    def _parse_qwen(text: str) -> list[tuple[str, str]]:
        pattern = r"Qwen3-Max\n\d{1,2}:\d{2}\s*[AP]M"
        parts = re.split(pattern, text)
        turns = []
        if parts[0].strip():
            turns.append(("user", parts[0].strip()))
        for part in parts[1:]:
            content = part.strip()
            if content:
                turns.append(("assistant", content))
        return turns

    @staticmethod
    def _parse_gemini(text: str) -> list[tuple[str, str]]:
        text = re.sub(r"^Conversation with Gemini\n", "", text).strip()
        if "--- USER ---" in text or "--- ASSISTANT ---" in text:
            return CopypasteWebParser._parse_manual_markers(text)
        parts = re.split(r"\n\n\n+", text, maxsplit=1)
        turns = []
        if parts[0].strip():
            turns.append(("user", parts[0].strip()))
        if len(parts) > 1 and parts[1].strip():
            turns.append(("assistant", parts[1].strip()))
        return turns
