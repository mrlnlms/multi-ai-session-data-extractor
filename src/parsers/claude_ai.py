"""Parser para dados exportados do Claude.ai."""

import json
from dataclasses import dataclass, asdict, fields
from pathlib import Path

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message

ROLE_MAP = {"human": "user", "assistant": "assistant"}


@dataclass
class ClaudeProject:
    project_id: str
    name: str
    description: str
    is_private: bool
    prompt_template: str
    created_at: pd.Timestamp
    updated_at: pd.Timestamp
    doc_count: int
    doc_names: str  # JSON array

    def to_dict(self) -> dict:
        return asdict(self)


class ClaudeAIParser(BaseParser):
    source_name = "claude_ai"

    def __init__(self, account: str | None = None):
        super().__init__(account)
        self.projects: list[ClaudeProject] = []

    def reset(self):
        super().reset()
        self.projects = []

    def parse_projects(self, input_path: Path) -> None:
        """Le projects.json e popula self.projects."""
        with open(input_path, encoding="utf-8") as f:
            raw_projects = json.load(f)

        for proj in raw_projects:
            docs = proj.get("docs") or []
            doc_names = [d.get("filename", "") for d in docs]

            self.projects.append(ClaudeProject(
                project_id=proj["uuid"],
                name=proj.get("name", ""),
                description=proj.get("description", ""),
                is_private=proj.get("is_private", True),
                prompt_template=proj.get("prompt_template", ""),
                created_at=self._ts(proj["created_at"]),
                updated_at=self._ts(proj["updated_at"]),
                doc_count=len(docs),
                doc_names=json.dumps(doc_names, ensure_ascii=False),
            ))

    def projects_df(self) -> pd.DataFrame:
        cols = [f.name for f in fields(ClaudeProject)]
        if not self.projects:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame([p.to_dict() for p in self.projects], columns=cols)

    def save(self, output_dir: Path) -> None:
        super().save(output_dir)

        proj_df = self.projects_df()
        if not proj_df.empty:
            proj_df.to_parquet(output_dir / f"{self.source_name}_project_metadata.parquet")

    def parse_files(self, input_paths: list[Path]) -> None:
        """Ingestao incremental: le cada conversations.json passado e acumula em self.

        Simetrico a parsers CLI. Uso tipico: passar apenas exports novos pra um
        upsert_unified() sem reparsear o historico todo.
        """
        for path in input_paths:
            self.parse(Path(path))

    def parse(self, input_path: Path) -> None:
        with open(input_path, encoding="utf-8") as f:
            conversations = json.load(f)

        for conv_data in conversations:
            chat_messages = conv_data.get("chat_messages", [])
            if not chat_messages:
                continue

            messages = self._extract_messages(conv_data["uuid"], chat_messages)

            title = conv_data.get("name") or None

            self.conversations.append(Conversation(
                conversation_id=conv_data["uuid"],
                source=self.source_name,
                title=title,
                created_at=self._ts(conv_data["created_at"]),
                updated_at=self._ts(conv_data["updated_at"]),
                message_count=len(messages),
                model=None,
                account=self.account,
                mode="chat",
                url=f"https://claude.ai/chat/{conv_data['uuid']}",
            ))
            self.messages.extend(messages)

    def _extract_messages(self, conv_id: str, chat_messages: list[dict]) -> list[Message]:
        messages = []

        for seq, msg_data in enumerate(chat_messages, start=1):
            sender = msg_data.get("sender", "")
            role = ROLE_MAP.get(sender)
            if role is None:
                continue

            content_blocks = msg_data.get("content", [])
            text_parts = []
            block_types = set()

            for block in content_blocks:
                btype = block.get("type", "text")
                block_types.add(btype)
                if btype == "text" and block.get("text"):
                    text_parts.append(block["text"])

            content = "\n\n".join(text_parts) if text_parts else ""

            file_names = []
            for f in msg_data.get("files", []):
                if f.get("file_name"):
                    file_names.append(f["file_name"])
            for a in msg_data.get("attachments", []):
                if a.get("file_name"):
                    file_names.append(a["file_name"])

            content_types = ",".join(sorted(block_types)) if block_types else "text"

            model = msg_data.get("model") if role == "assistant" else None

            messages.append(Message(
                message_id=msg_data["uuid"],
                conversation_id=conv_id,
                source=self.source_name,
                sequence=seq,
                role=role,
                content=content,
                model=model,
                created_at=self._ts(msg_data["created_at"]),
                account=self.account,
                content_types=content_types,
                attachment_names=json.dumps(file_names) if file_names else None,
            ))

        return messages
