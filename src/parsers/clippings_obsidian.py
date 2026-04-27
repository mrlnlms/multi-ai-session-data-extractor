"""Parser para clippings Obsidian (Markdown com YAML frontmatter).

Formato: Obsidian Web Clipper exporta conversas ChatGPT/Claude.ai
como markdown com frontmatter YAML. User turns em blockquote (>),
assistant turns em texto plano.
"""

import logging
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import yaml

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message

logger = logging.getLogger(__name__)

# Mapping author field to source name
AUTHOR_TO_SOURCE = {
    "ChatGPT": "chatgpt",
    "Claude": "claude_ai",
}


class ClippingsObsidianParser(BaseParser):
    source_name = "clippings_obsidian"

    def parse(self, input_path: Path) -> None:
        """Parse all .md files in the input directory."""
        input_path = Path(input_path)
        md_files = sorted(input_path.glob("*.md"))

        for md_file in md_files:
            self._parse_file(md_file)

    def _parse_file(self, file_path: Path) -> None:
        text = file_path.read_text(encoding="utf-8")

        # Split frontmatter from body
        parts = text.split("---", 2)
        if len(parts) < 3:
            logger.warning(f"Skipping {file_path.name}: no YAML frontmatter")
            return

        meta = yaml.safe_load(parts[1])
        body = parts[2].strip()

        # Extract source from author
        author_raw = meta.get("author", [])
        if isinstance(author_raw, list) and author_raw:
            author_raw = author_raw[0]
        author_clean = re.sub(r"\[\[|\]\]", "", str(author_raw))
        source = AUTHOR_TO_SOURCE.get(author_clean, "chatgpt")

        # Extract conversation_id from URL
        source_url = meta.get("source", "")
        conv_id = self._extract_conv_id(source_url)

        # Extract title from filename (strip date prefix)
        stem = file_path.stem
        title_match = re.match(r"\d{4}-\d{2}-\d{2}\s*-\s*(.+)", stem)
        title = title_match.group(1).strip() if title_match else stem

        created = self._ts(meta.get("created"))

        # Parse turns
        turns = self._parse_turns(body)
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
        ))
        self.messages.extend(messages)

    @staticmethod
    def _extract_conv_id(url: str) -> str:
        """Extract conversation UUID from ChatGPT/Claude URL."""
        if not url:
            return str(uuid.uuid4())
        path = urlparse(url).path
        # Last segment of URL path is the conversation ID
        segments = [s for s in path.split("/") if s]
        return segments[-1] if segments else str(uuid.uuid4())

    @staticmethod
    def _parse_turns(body: str) -> list[tuple[str, str]]:
        """Parse markdown body into (role, content) tuples.

        User turns are in blockquotes (lines starting with >).
        Assistant turns are plain text between blockquotes.
        """
        turns = []
        current_role = None
        current_lines = []

        for line in body.split("\n"):
            stripped = line.strip()

            if stripped.startswith(">"):
                # User turn line — strip the > prefix
                content_line = re.sub(r"^>\s?", "", stripped)
                if current_role == "user":
                    current_lines.append(content_line)
                else:
                    # Flush previous assistant turn
                    if current_role == "assistant" and current_lines:
                        text = "\n".join(current_lines).strip()
                        if text:
                            turns.append(("assistant", text))
                    current_role = "user"
                    current_lines = [content_line]
            else:
                if current_role == "user" and stripped == "":
                    # Blank line after blockquote — flush user turn
                    if current_lines:
                        text = "\n".join(current_lines).strip()
                        if text:
                            turns.append(("user", text))
                    current_role = None
                    current_lines = []
                elif current_role == "user":
                    # Non-blockquote line right after blockquote without blank line
                    # Flush user turn, start assistant
                    if current_lines:
                        text = "\n".join(current_lines).strip()
                        if text:
                            turns.append(("user", text))
                    current_role = "assistant"
                    current_lines = [line.rstrip()]
                elif current_role == "assistant":
                    current_lines.append(line.rstrip())
                elif current_role is None and stripped:
                    # Non-blockquote content — assistant turn
                    current_role = "assistant"
                    current_lines = [line.rstrip()]

        # Flush last turn
        if current_role and current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                turns.append((current_role, text))

        return turns
