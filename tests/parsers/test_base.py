# tests/parsers/test_base.py
import pytest
from pathlib import Path
from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message


class FakeParser(BaseParser):
    """Parser concreto minimo pra testar a interface."""

    source_name = "claude_ai"

    def parse(self, input_path: Path) -> None:
        self.conversations.append(
            Conversation(
                conversation_id=f"{self.source_name}_1",
                source=self.source_name,
                title="Fake chat",
                created_at=self._ts("2026-01-01"),
                updated_at=self._ts("2026-01-01"),
                message_count=1,
                model="fake-model",
            )
        )
        self.messages.append(
            Message(
                message_id="msg_1",
                conversation_id=f"{self.source_name}_1",
                source=self.source_name,
                sequence=1,
                role="user",
                content="Hello",
                model=None,
                created_at=self._ts("2026-01-01 10:00:00"),
            )
        )


def test_parser_parse_populates_lists():
    parser = FakeParser()
    parser.parse(Path("/fake"))
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 1


def test_parser_to_dataframes():
    parser = FakeParser()
    parser.parse(Path("/fake"))
    conv_df = parser.conversations_df()
    msg_df = parser.messages_df()
    assert len(conv_df) == 1
    assert len(msg_df) == 1
    assert conv_df.iloc[0]["source"] == "claude_ai"


def test_parser_save_parquet(tmp_path):
    parser = FakeParser()
    parser.parse(Path("/fake"))
    parser.save(tmp_path)
    assert (tmp_path / "claude_ai_conversations.parquet").exists()
    assert (tmp_path / "claude_ai_messages.parquet").exists()


def test_parser_save_computes_word_count(tmp_path):
    import pandas as pd
    parser = FakeParser()
    parser.parse(Path("/fake"))
    parser.save(tmp_path)
    df = pd.read_parquet(tmp_path / "claude_ai_messages.parquet")
    assert "word_count" in df.columns
    assert df.iloc[0]["word_count"] == 1  # "Hello" = 1 word


def test_parser_reset():
    parser = FakeParser()
    parser.parse(Path("/fake"))
    assert len(parser.conversations) == 1
    parser.reset()
    assert len(parser.conversations) == 0
    assert len(parser.messages) == 0


class FakeParserWithAccount(BaseParser):
    source_name = "gemini"

    def parse(self, input_path: Path) -> None:
        self.conversations.append(
            Conversation(
                conversation_id="gemini_1",
                source=self.source_name,
                title="Test",
                created_at=self._ts("2025-04-10"),
                updated_at=self._ts("2025-04-10"),
                message_count=1,
                model="gemini-pro",
                account=self.account,
            )
        )


def test_parser_account_parameter():
    parser = FakeParserWithAccount(account="pessoal")
    parser.parse(Path("/fake"))
    assert parser.account == "pessoal"
    assert parser.conversations[0].account == "pessoal"


def test_parser_account_default_none():
    parser = FakeParserWithAccount()
    assert parser.account is None


def test_ts_none_returns_nat():
    import pandas as pd
    result = FakeParser._ts(None)
    assert pd.isna(result)


def test_ts_valid_string():
    import pandas as pd
    # ISO sem TZ → assume UTC → converte pra BRT (-3h) naive
    result = FakeParser._ts("2026-01-01")
    assert result == pd.Timestamp("2025-12-31 21:00:00")


def test_ts_iso_with_tz_converted_to_brt():
    import pandas as pd
    # 2026-02-25T09:40:43+03:00 == 06:40:43 UTC == 03:40:43 BRT
    result = FakeParser._ts("2026-02-25T09:40:43+03:00")
    assert result == pd.Timestamp("2026-02-25 03:40:43")


def test_ts_iso_with_z_converted_to_brt():
    import pandas as pd
    # Z == UTC
    result = FakeParser._ts("2026-02-25T12:38:27.901933Z")
    assert result == pd.Timestamp("2026-02-25 09:38:27.901933")


def test_ts_epoch_int_converted_to_brt():
    import pandas as pd
    # epoch 1772023105 (inteiro) == 2026-02-25 12:38:25 UTC == 09:38:25 BRT
    result = FakeParser._ts(1772023105)
    assert result == pd.Timestamp("2026-02-25 09:38:25")
