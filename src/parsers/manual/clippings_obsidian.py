"""Parser pra clippings do Obsidian Web Clipper.

Formato: markdown com YAML frontmatter. User turns em blockquote (>),
assistant turns em texto plano.

source = plataforma original (extraida do `author` no frontmatter):
  ChatGPT → 'chatgpt', Claude → 'claude_ai'
capture_method = 'manual_clipping_obsidian'
"""

from __future__ import annotations

import logging
import re
import uuid as uuid_lib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pandas as pd
import yaml

from src.parsers.base import BaseParser
from src.schema.models import (
    Branch,
    Conversation,
    Message,
)


logger = logging.getLogger(__name__)


# Mapping author no frontmatter → source canonico
AUTHOR_TO_SOURCE = {
    "ChatGPT": "chatgpt",
    "Claude": "claude_ai",
    "Gemini": "gemini",
    "Qwen": "qwen",
    "DeepSeek": "deepseek",
    "Perplexity": "perplexity",
}


CAPTURE_METHOD = "manual_clipping_obsidian"


class ClippingsObsidianParser(BaseParser):
    """Parser canonico v3 — output: source=plataforma_original, capture_method=manual_clipping_obsidian."""

    source_name = "clippings_obsidian"  # nome do parser (nao do source)

    def __init__(self, account: Optional[str] = None):
        super().__init__(account=account)
        self.branches: list[Branch] = []

    def reset(self):
        super().reset()
        self.branches = []

    def parse(self, input_path: Path) -> None:
        input_path = Path(input_path)
        for md_file in sorted(input_path.glob("*.md")):
            self._parse_file(md_file)
        self._build_branches()

    def _build_branches(self) -> None:
        """1 Branch <conv>_main por Conversation."""
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
                source=conv.source,  # plataforma original
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

        # Split frontmatter from body
        parts = text.split("---", 2)
        if len(parts) < 3:
            logger.warning(f"  {file_path.name}: sem YAML frontmatter")
            return

        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError as e:
            logger.warning(f"  {file_path.name}: YAML invalido: {e}")
            return
        body = parts[2].strip()

        # Source da plataforma original
        author_raw = meta.get("author", [])
        if isinstance(author_raw, list) and author_raw:
            author_raw = author_raw[0]
        author_clean = re.sub(r"\[\[|\]\]", "", str(author_raw))
        source = AUTHOR_TO_SOURCE.get(author_clean, "chatgpt")  # fallback chatgpt

        # Conv ID extraído da URL
        source_url = meta.get("source", "")
        conv_id = self._extract_conv_id(source_url)

        # Title: filename strip date prefix
        stem = file_path.stem
        title_match = re.match(r"\d{4}-\d{2}-\d{2}\s*-\s*(.+)", stem)
        title = title_match.group(1).strip() if title_match else stem

        created = self._ts(meta.get("created"))

        turns = self._parse_turns(body)
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
                created_at=created,
                account=self.account,
                content_types="text",
            ))

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=source,
            title=title,
            created_at=created,
            updated_at=created,
            message_count=len(messages),
            model=None,
            account=self.account,
            url=source_url or None,
            capture_method=CAPTURE_METHOD,
        ))
        self.messages.extend(messages)

    @staticmethod
    def _extract_conv_id(url: str) -> str:
        """Extrai conversation UUID do URL ChatGPT/Claude.ai."""
        if not url:
            return str(uuid_lib.uuid4())
        path = urlparse(url).path
        segments = [s for s in path.split("/") if s]
        return segments[-1] if segments else str(uuid_lib.uuid4())

    @staticmethod
    def _parse_turns(body: str) -> list[tuple[str, str]]:
        """User turns em blockquotes (>), assistant em texto plano entre blockquotes."""
        turns: list[tuple[str, str]] = []
        current_role: Optional[str] = None
        current_lines: list[str] = []

        for line in body.split("\n"):
            stripped = line.strip()

            if stripped.startswith(">"):
                content_line = re.sub(r"^>\s?", "", stripped)
                if current_role == "user":
                    current_lines.append(content_line)
                else:
                    if current_role == "assistant" and current_lines:
                        text = "\n".join(current_lines).strip()
                        if text:
                            turns.append(("assistant", text))
                    current_role = "user"
                    current_lines = [content_line]
            else:
                if current_role == "user" and stripped == "":
                    if current_lines:
                        text = "\n".join(current_lines).strip()
                        if text:
                            turns.append(("user", text))
                    current_role = None
                    current_lines = []
                elif current_role == "user":
                    if current_lines:
                        text = "\n".join(current_lines).strip()
                        if text:
                            turns.append(("user", text))
                    current_role = "assistant"
                    current_lines = [line.rstrip()]
                elif current_role == "assistant":
                    current_lines.append(line.rstrip())
                elif current_role is None and stripped:
                    current_role = "assistant"
                    current_lines = [line.rstrip()]

        if current_role and current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                turns.append((current_role, text))

        return turns
