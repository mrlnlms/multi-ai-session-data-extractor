"""Parser para metadados de notebooks do NotebookLM (scrapeados em markdown).

Suporta duas fontes:
- Inventarios markdown (parse): titulo, datas, sources, UUID
- Downloads Playwright (parse_downloads): chat, notes, guide, audio metadata
- Metadados notebook.json (parse_downloads): guide_summary, sources
"""

import json
import logging
import re
from pathlib import Path
from dataclasses import dataclass, asdict, fields

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message

logger = logging.getLogger(__name__)


@dataclass
class NotebookGuide:
    conversation_id: str
    guide_summary: str
    source_count: int
    source_names: str  # JSON array of source names

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NotebookSource:
    conversation_id: str
    source_uuid: str
    source_name: str

    def to_dict(self) -> dict:
        return asdict(self)

# Meses em portugues abreviado
_PT_MONTHS = {
    "jan.": 1, "fev.": 2, "mar.": 3, "abr.": 4,
    "mai.": 5, "jun.": 6, "jul.": 7, "ago.": 8,
    "set.": 9, "out.": 10, "nov.": 11, "dez.": 12,
}

_UUID_RE = re.compile(r"/notebook/([0-9a-f-]{36})")


class NotebookLMParser(BaseParser):
    source_name = "notebooklm"

    def __init__(self, account: str | None = None):
        super().__init__(account)
        self.guides: list[NotebookGuide] = []
        self.sources: list[NotebookSource] = []

    def reset(self):
        super().reset()
        self.guides = []
        self.sources = []

    def parse(self, input_path: Path) -> None:
        text = input_path.read_text(encoding="utf-8")

        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.split("|")]
            # Remove empty strings from split
            cells = [c for c in cells if c]

            # Skip header and separator rows
            if not cells or cells[0] == "#" or cells[0].startswith("-"):
                continue

            # First cell should be a number
            try:
                int(cells[0])
            except ValueError:
                continue

            uuid = self._extract_uuid(cells)
            if not uuid:
                continue

            if len(cells) >= 7:
                conv = self._parse_7col(cells, uuid)
            elif len(cells) >= 5:
                conv = self._parse_5col(cells, uuid)
            else:
                continue

            if conv:
                self.conversations.append(conv)

    def _extract_uuid(self, cells: list[str]) -> str | None:
        for cell in cells:
            m = _UUID_RE.search(cell)
            if m:
                return m.group(1)
        return None

    def _parse_7col(self, cells: list[str], uuid: str) -> Conversation:
        """Parse: # | Titulo | Criado | Atualizado | Sources | Fontes | Link"""
        title = cells[1]
        created_at = self._ts(cells[2])
        updated_at = self._ts(cells[3])

        return Conversation(
            conversation_id=uuid,
            source=self.source_name,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            message_count=0,
            model=None,
            account=self.account,
            url=f"https://notebooklm.google.com/notebook/{uuid}",
        )

    def _parse_5col(self, cells: list[str], uuid: str) -> Conversation:
        """Parse: # | Titulo | Data | Sources | Link"""
        title = cells[1]
        created_at = self._parse_pt_date(cells[2])

        return Conversation(
            conversation_id=uuid,
            source=self.source_name,
            title=title,
            created_at=created_at,
            updated_at=created_at,
            message_count=0,
            model=None,
            account=self.account,
            url=f"https://notebooklm.google.com/notebook/{uuid}",
        )

    def parse_downloads(self, downloads_dir: Path) -> None:
        """Le chat.json e notebook.json dos notebooks baixados.

        - chat.json → Messages + atualiza message_count
        - notebook.json → guides (guide_summary) + sources
        downloads_dir deve ser a pasta da conta (ex: data/raw/NotebookLM Data/more.design/).
        """
        existing_convs = {c.conversation_id: c for c in self.conversations}

        for chat_file in downloads_dir.glob("*/chat.json"):
            uuid = chat_file.parent.name
            if uuid not in existing_convs:
                continue  # Skip orphan: chat sem conversa no inventario
            chat = json.loads(chat_file.read_text(encoding="utf-8"))
            if not chat:
                continue

            messages = []

            # Briefs como contexto (sequence=0, role=system)
            brief_content = self._read_briefs(chat_file.parent)
            if brief_content:
                first_ts = pd.NaT
                if chat and chat[0].get("timestamp"):
                    first_ts = self._ts(chat[0]["timestamp"])
                messages.append(Message(
                    message_id=f"{uuid}_brief",
                    conversation_id=uuid,
                    source=self.source_name,
                    sequence=0,
                    role="system",
                    content=brief_content,
                    model=None,
                    created_at=first_ts,
                    account=self.account,
                    content_types="brief",
                ))

            for seq, msg in enumerate(chat, 1):
                ts = self._ts(msg["timestamp"]) if msg.get("timestamp") else pd.NaT
                messages.append(Message(
                    message_id=msg.get("id", f"{uuid}_{seq}"),
                    conversation_id=uuid,
                    source=self.source_name,
                    sequence=seq,
                    role=msg["role"],
                    content=msg.get("content", ""),
                    model=None,
                    created_at=ts,
                    account=self.account,
                    content_types="text",
                ))

            self.messages.extend(messages)

            # Atualizar message_count se a conversa ja existe
            if uuid in existing_convs:
                existing_convs[uuid].message_count = len(messages)

        # notebook.json → guides + sources
        for nb_file in downloads_dir.glob("*/notebook.json"):
            uuid = nb_file.parent.name
            if uuid not in existing_convs:
                continue  # Skip orphan: notebook sem conversa no inventario
            nb = json.loads(nb_file.read_text(encoding="utf-8"))

            # Guide summary
            guide = nb.get("guide") or {}
            summary = guide.get("summary", "")

            # Sources
            nb_sources = nb.get("sources") or []
            source_names = [s.get("name", "") for s in nb_sources]

            if summary or nb_sources:
                self.guides.append(NotebookGuide(
                    conversation_id=uuid,
                    guide_summary=summary,
                    source_count=len(nb_sources),
                    source_names=json.dumps(source_names, ensure_ascii=False),
                ))

            for s in nb_sources:
                self.sources.append(NotebookSource(
                    conversation_id=uuid,
                    source_uuid=s.get("uuid", ""),
                    source_name=s.get("name", ""),
                ))

    def guides_df(self) -> pd.DataFrame:
        cols = [f.name for f in fields(NotebookGuide)]
        if not self.guides:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame([g.to_dict() for g in self.guides], columns=cols)

    def sources_df(self) -> pd.DataFrame:
        cols = [f.name for f in fields(NotebookSource)]
        if not self.sources:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame([s.to_dict() for s in self.sources], columns=cols)

    def save(self, output_dir: Path) -> None:
        super().save(output_dir)

        guides = self.guides_df()
        if not guides.empty:
            guides.to_parquet(output_dir / f"{self.source_name}_guides.parquet")

        sources = self.sources_df()
        if not sources.empty:
            sources.to_parquet(output_dir / f"{self.source_name}_sources.parquet")

    @staticmethod
    def _read_briefs(notebook_dir: Path) -> str:
        """Concatena todos os *_brief.md de um notebook em um unico texto."""
        briefs = sorted(notebook_dir.glob("audio/*_brief.md"))
        if not briefs:
            return ""
        parts = []
        for b in briefs:
            content = b.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
        return "\n\n---\n\n".join(parts)

    def _parse_pt_date(self, text: str) -> pd.Timestamp:
        """Parse '25 de mai. de 2025' → Timestamp BRT naive."""
        parts = text.strip().split()
        # Expected: ['25', 'de', 'mai.', 'de', '2025']
        if len(parts) >= 5:
            day = int(parts[0])
            month = _PT_MONTHS.get(parts[2], 1)
            year = int(parts[4])
            # Data local (sem hora) — interpretada como BRT, sem conversao
            return pd.Timestamp(year=year, month=month, day=day)
        # Fallback: parse string via _ts (assume UTC se sem TZ)
        return self._ts(text)
