# src/parsers/base.py
"""Interface base para parsers de cada fonte de AI."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

from src.schema.models import (
    Conversation,
    Message,
    ToolEvent,
    conversations_to_df,
    messages_to_df,
    tool_events_to_df,
)


class BaseParser(ABC):
    """Classe base que todo parser de fonte deve estender.

    Subclasses implementam parse() para popular self.conversations,
    self.messages e opcionalmente self.events.
    """

    source_name: str = ""

    def __init__(self, account: str | None = None):
        self.account = account
        self.reset()

    def reset(self):
        self.conversations: list[Conversation] = []
        self.messages: list[Message] = []
        self.events: list[ToolEvent] = []

    @abstractmethod
    def parse(self, input_path: Path) -> None:
        """Le o arquivo/diretorio de input e popula conversations e messages."""
        ...

    def conversations_df(self) -> pd.DataFrame:
        return conversations_to_df(self.conversations)

    def messages_df(self) -> pd.DataFrame:
        return messages_to_df(self.messages)

    def events_df(self) -> pd.DataFrame:
        return tool_events_to_df(self.events)

    def save(self, output_dir: Path) -> None:
        """Salva DataFrames como parquet no diretorio de output."""
        output_dir.mkdir(parents=True, exist_ok=True)

        conv_df = self.conversations_df()
        if not conv_df.empty:
            conv_df.to_parquet(output_dir / f"{self.source_name}_conversations.parquet")

        msg_df = self.messages_df()
        if not msg_df.empty:
            msg_df["word_count"] = msg_df["content"].fillna("").str.split().str.len()
            msg_df.to_parquet(output_dir / f"{self.source_name}_messages.parquet")

        evt_df = self.events_df()
        if not evt_df.empty:
            # Convencao canonica: tool_events.parquet (alinha com todas as
            # subclasses concretas que ja sobrescrevem save()).
            evt_df.to_parquet(output_dir / f"{self.source_name}_tool_events.parquet")

    @staticmethod
    def _ts(value) -> pd.Timestamp:
        """Normaliza timestamp pra America/Sao_Paulo (BRT) naive.

        Aceita:
        - None / NaN → NaT
        - int/float → epoch em segundos (UTC)
        - str ISO com TZ → respeita o offset
        - str ISO sem TZ → assume UTC (padrao dos exports Claude/ChatGPT)
        """
        if value is None:
            return pd.NaT
        if isinstance(value, float) and pd.isna(value):
            return pd.NaT
        if isinstance(value, (int, float)):
            ts = pd.Timestamp(value, unit="s", tz="UTC")
        else:
            ts = pd.Timestamp(value)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
        return ts.tz_convert("America/Sao_Paulo").tz_localize(None)
