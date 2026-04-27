import json
import pytest
import pandas as pd
from pathlib import Path
from src.parsers.perplexity import PerplexityParser


FIXTURE = [
    {
        "thread_number": 0,
        "uuid": "thread-001",
        "frontend_uuid": "fe-001",
        "title": "HAI research",
        "query_str": "What is HAI?",
        "last_query_datetime": "2025-09-05T10:12:00Z",
        "mode": "copilot",
        "display_model": "turbo",
        "status": "COMPLETED",
        "query_count": 3,
        "extracted_messages": [
            {"role": "user", "text": "What is HAI?"},
            {"role": "assistant", "text": "Human-AI Interaction is..."},
            {"role": "user", "text": "Tell me more"},
            {"role": "assistant", "text": "HAI research focuses on..."},
        ],
    },
    {
        "thread_number": 1,
        "uuid": "thread-002",
        "frontend_uuid": "fe-002",
        "title": "Deep research test",
        "query_str": "Comprehensive analysis",
        "last_query_datetime": "2025-09-10T14:00:00Z",
        "mode": "research",
        "display_model": "default",
        "status": "COMPLETED",
        "query_count": 1,
        "extracted_messages": [
            {"role": "user", "text": "Comprehensive analysis of X"},
            {"role": "assistant", "text": "Based on extensive research..."},
        ],
    },
]


def _write_fixture(tmp_path, data):
    p = tmp_path / "export.json"
    p.write_text(json.dumps(data))
    return p


def test_perplexity_basic(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = PerplexityParser()
    parser.parse(path)
    assert len(parser.conversations) == 2
    assert len(parser.messages) == 6
    conv = parser.conversations[0]
    assert conv.conversation_id == "thread-001"
    assert conv.source == "perplexity"
    assert conv.title == "HAI research"
    assert conv.mode == "copilot"
    assert conv.model == "turbo"
    assert conv.message_count == 4


def test_perplexity_research_mode(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = PerplexityParser()
    parser.parse(path)
    conv = parser.conversations[1]
    assert conv.mode == "research"


def test_perplexity_timestamps_fallback(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = PerplexityParser()
    parser.parse(path)
    for msg in parser.messages[:4]:
        # 10:12 UTC → 07:12 BRT
        assert msg.created_at == pd.Timestamp("2025-09-05 07:12:00")


def test_perplexity_roles(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = PerplexityParser()
    parser.parse(path)
    roles = [m.role for m in parser.messages[:4]]
    assert roles == ["user", "assistant", "user", "assistant"]
