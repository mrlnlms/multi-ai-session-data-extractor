"""Parser para conversas copiadas manualmente da web (plaintext).

Formato: arquivos .txt com conversas copiadas de interfaces web.
Cada arquivo tem marcadores diferentes dependendo da plataforma:
- GPT.txt: "ChatGPT said:" separa resposta
- QWEEN.txt: "Qwen3-Max" + timestamp separa respostas
- GEMINI-hello.txt: "Conversation with Gemini" header
- CLAUDE.txt, GEMINI-marlooon.txt: marcadores manuais "--- USER ---"/"--- ASSISTANT ---"
"""

import logging
import os
import re
import uuid
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message

logger = logging.getLogger(__name__)

# Filename prefix to source mapping
FILENAME_TO_SOURCE = {
    "CLAUDE": "claude_ai",
    "GPT": "chatgpt",
    "GEMINI": "gemini",
    "QWEEN": "qwen",
}


class CopypasteWebParser(BaseParser):
    source_name = "copypaste_web"

    def parse(self, input_path: Path) -> None:
        """Parse all .txt files in the input directory."""
        input_path = Path(input_path)
        txt_files = sorted(input_path.glob("*.txt"))

        for txt_file in txt_files:
            self._parse_file(txt_file)

    def _parse_file(self, file_path: Path) -> None:
        text = file_path.read_text(encoding="utf-8")
        stem = file_path.stem
        source = self._detect_source(stem)
        conv_id = f"manual_copypaste_{stem.lower()}"
        file_ts = self._ts(os.path.getmtime(file_path))

        # Parse turns based on format
        turns = self._parse_turns(text, stem)
        if not turns:
            logger.warning(f"Skipping {file_path.name}: no turns found")
            return

        messages = []
        for seq, (role, content) in enumerate(turns, start=1):
            messages.append(Message(
                message_id=str(uuid.uuid4()),
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
        """Route to format-specific parser based on filename."""
        upper = stem.upper()

        if "--- USER ---" in text or "--- ASSISTANT ---" in text:
            return CopypasteWebParser._parse_manual_markers(text)
        elif upper.startswith("GPT"):
            return CopypasteWebParser._parse_gpt(text)
        elif upper.startswith("QWEEN"):
            return CopypasteWebParser._parse_qwen(text)
        elif upper.startswith("GEMINI"):
            return CopypasteWebParser._parse_gemini(text)
        else:
            # Fallback: entire content as single user message
            return [("user", text.strip())]

    @staticmethod
    def _parse_manual_markers(text: str) -> list[tuple[str, str]]:
        """Parse files with --- USER --- / --- ASSISTANT --- markers."""
        parts = re.split(r"---\s*(USER|ASSISTANT)\s*---", text)
        turns = []
        i = 1  # skip text before first marker
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
        """Parse GPT format: user content then 'ChatGPT said:' marker."""
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
        """Parse Qwen format: 'Qwen3-Max' + timestamp markers."""
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
        """Parse Gemini format: optional 'Conversation with Gemini' header."""
        # Remove header if present
        text = re.sub(r"^Conversation with Gemini\n", "", text).strip()

        # If manual markers are present, use that parser
        if "--- USER ---" in text or "--- ASSISTANT ---" in text:
            return CopypasteWebParser._parse_manual_markers(text)

        # Fallback: first block is user, rest is assistant
        # Split on first double blank line
        parts = re.split(r"\n\n\n+", text, maxsplit=1)
        turns = []
        if parts[0].strip():
            turns.append(("user", parts[0].strip()))
        if len(parts) > 1 and parts[1].strip():
            turns.append(("assistant", parts[1].strip()))
        return turns
