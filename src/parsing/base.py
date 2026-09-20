# src/parsing/base.py
"""Interface base para parsers de cada fonte de AI."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from src.assets.reader import (
    AssetReader,
    apply_asset_projection,
    combine_asset_projections,
)
from src.assets.appearances import commit_web_parser_appearances
from src.assets.runtime import load_asset_runtime

logger = logging.getLogger(__name__)

WEB_ASSET_SOURCES = frozenset({
    "chatgpt", "claude_ai", "gemini", "notebooklm", "qwen",
    "deepseek", "perplexity", "grok", "kimi",
})

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

    def __init__(
        self,
        account: str | None = None,
        account_id: str | None = None,
        *,
        asset_reader: AssetReader | None = None,
    ):
        self.web_asset_vault = None
        if asset_reader is None and self.source_name:
            runtime = load_asset_runtime(self.source_name)
            asset_reader = runtime.reader
            self.web_asset_vault = runtime.vault
        self.account = account
        self.account_id = account_id
        self.asset_reader = asset_reader
        self.asset_projection = None
        self.reset()

    def reset(self):
        self.conversations: list[Conversation] = []
        self.messages: list[Message] = []
        self.events: list[ToolEvent] = []
        self.asset_projection = None

    def apply_asset_reader(self, account_ids=None):
        """Apply the explicitly injected reader after source parsing completes."""
        if self.asset_reader is None:
            return None
        if (
            self.web_asset_vault is not None
            and self.source_name in WEB_ASSET_SOURCES
            and hasattr(self, "assets")
            and hasattr(self, "asset_links")
        ):
            commit_web_parser_appearances(
                self.web_asset_vault,
                source=self.source_name,
                assets=tuple(self.assets),
                links=tuple(self.asset_links),
                messages=tuple(self.messages),
                evidence_path=Path(getattr(self, "raw_root", ".")),
            )
        if account_ids is None:
            account_ids = (self.account_id,)
        projection = combine_asset_projections(
            self.asset_reader, self.source_name, account_ids
        )
        apply_asset_projection(self.messages, projection)
        self.asset_projection = projection
        if hasattr(self, "assets"):
            self.assets = list(projection.assets)
        if hasattr(self, "asset_links"):
            self.asset_links = list(projection.links)
        return projection

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
