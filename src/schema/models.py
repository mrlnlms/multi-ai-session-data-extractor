# src/schema/models.py
"""Schema unificado para dados de interacao com AI."""

from dataclasses import dataclass, fields, asdict
from typing import Optional

import pandas as pd


VALID_SOURCES = ("claude_ai", "chatgpt", "chatgpt_v2", "qwen", "claude_code", "deepseek", "perplexity", "gemini", "notebooklm", "codex", "gemini_cli")
VALID_ROLES = ("user", "assistant", "system")
VALID_MODES = ("chat", "search", "research", "copilot", "concise", "dalle", "cli")


@dataclass
class Conversation:
    conversation_id: str
    source: str
    title: Optional[str]
    created_at: pd.Timestamp
    updated_at: pd.Timestamp
    message_count: int
    model: Optional[str]
    account: Optional[str] = None
    mode: Optional[str] = None
    project: Optional[str] = None
    url: Optional[str] = None
    interaction_type: str = "human_ai"
    parent_session_id: Optional[str] = None

    def __post_init__(self):
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source '{self.source}' invalido. Validos: {VALID_SOURCES}")
        if self.mode is not None and self.mode not in VALID_MODES:
            raise ValueError(f"mode '{self.mode}' invalido. Validos: {VALID_MODES}")
        if self.interaction_type not in ("human_ai", "ai_ai"):
            raise ValueError(f"interaction_type '{self.interaction_type}' invalido. Validos: human_ai, ai_ai")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    message_id: str
    conversation_id: str
    source: str
    sequence: int
    role: str
    content: str
    model: Optional[str]
    created_at: pd.Timestamp
    account: Optional[str] = None
    token_count: Optional[int] = None
    word_count: Optional[int] = None
    attachment_names: Optional[str] = None
    content_types: Optional[str] = None
    thinking: Optional[str] = None
    tool_results: Optional[str] = None

    def __post_init__(self):
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source '{self.source}' invalido. Validos: {VALID_SOURCES}")
        if self.role not in VALID_ROLES:
            raise ValueError(f"role '{self.role}' invalido. Validos: {VALID_ROLES}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ToolEvent:
    event_id: str
    conversation_id: str
    message_id: str
    source: str
    event_type: str
    tool_name: Optional[str] = None
    file_path: Optional[str] = None
    command: Optional[str] = None
    duration_ms: Optional[int] = None
    success: Optional[bool] = None
    metadata_json: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConversationProject:
    conversation_id: str
    project_tag: str
    tagged_by: str
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _models_to_df(items: list, column_order: list[str]) -> pd.DataFrame:
    """Converte lista de dataclasses em DataFrame com colunas ordenadas."""
    if not items:
        return pd.DataFrame(columns=column_order)
    rows = [item.to_dict() for item in items]
    return pd.DataFrame(rows, columns=column_order)


def conversations_to_df(convs: list[Conversation]) -> pd.DataFrame:
    cols = [f.name for f in fields(Conversation)]
    return _models_to_df(convs, cols)


def messages_to_df(msgs: list[Message]) -> pd.DataFrame:
    cols = [f.name for f in fields(Message)]
    return _models_to_df(msgs, cols)


def tool_events_to_df(events: list[ToolEvent]) -> pd.DataFrame:
    cols = [f.name for f in fields(ToolEvent)]
    return _models_to_df(events, cols)


def conversation_projects_to_df(projects: list[ConversationProject]) -> pd.DataFrame:
    cols = [f.name for f in fields(ConversationProject)]
    return _models_to_df(projects, cols)
