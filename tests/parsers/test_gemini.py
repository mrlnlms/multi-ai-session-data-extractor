import json
import pytest
from pathlib import Path
from src.parsers.gemini import GeminiParser
import pandas as pd


FIXTURE = [
    {
        "index": 0,
        "href": "/app/abc123def456",
        "title": "Resume article",
        "url": "https://gemini.google.com/app/abc123def456",
        "message_count": 2,
        "messages": [
            {
                "turn_id": "turn-1",
                "user": "Summarize this article",
                "model": "Here is a summary of the article...",
            },
            {
                "turn_id": "turn-2",
                "user": "Can you elaborate on point 3?",
                "model": "Point 3 discusses...",
            },
        ],
        "first_timestamp": "2025-04-10T11:00:00Z",
        "last_timestamp": "2025-04-10T11:15:00Z",
    },
]

FIXTURE_NO_TIMESTAMPS = [
    {
        "index": 0,
        "href": "/app/xyz789",
        "title": "No timestamps",
        "url": "https://gemini.google.com/app/xyz789",
        "message_count": 1,
        "messages": [
            {
                "turn_id": "turn-1",
                "user": "Hello",
                "model": "Hi!",
            },
        ],
    },
]


def _write_fixture(tmp_path, data):
    p = tmp_path / "gemini-enriched.json"
    p.write_text(json.dumps(data))
    return p


def test_gemini_basic(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = GeminiParser(account="pessoal")
    parser.parse(path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 4
    conv = parser.conversations[0]
    assert conv.conversation_id == "pessoal_abc123def456"
    assert conv.source == "gemini"
    assert conv.title == "Resume article"
    assert conv.account == "pessoal"
    assert conv.mode == "chat"
    assert conv.message_count == 4


def test_gemini_turn_to_two_messages(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = GeminiParser(account="pessoal")
    parser.parse(path)
    assert parser.messages[0].role == "user"
    assert parser.messages[0].sequence == 1
    assert parser.messages[0].content == "Summarize this article"
    assert parser.messages[1].role == "assistant"
    assert parser.messages[1].sequence == 2
    assert parser.messages[1].content == "Here is a summary of the article..."


def test_gemini_account_propagated(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = GeminiParser(account="trabalho")
    parser.parse(path)
    assert parser.conversations[0].account == "trabalho"
    assert parser.messages[0].account == "trabalho"


def test_gemini_no_timestamps(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_NO_TIMESTAMPS)
    parser = GeminiParser(account="pessoal")
    parser.parse(path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2


def test_gemini_conv_id_from_href(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = GeminiParser(account="pessoal")
    parser.parse(path)
    assert parser.conversations[0].conversation_id == "pessoal_abc123def456"


def test_gemini_different_accounts_no_collision(tmp_path):
    """Duas contas com mesmo href nao colidem."""
    path = _write_fixture(tmp_path, FIXTURE)

    p1 = GeminiParser(account="pessoal")
    p1.parse(path)
    p2 = GeminiParser(account="trabalho")
    p2.parse(path)

    id1 = p1.conversations[0].conversation_id
    id2 = p2.conversations[0].conversation_id
    assert id1 != id2
    assert id1 == "pessoal_abc123def456"
    assert id2 == "trabalho_abc123def456"

    # Message IDs tambem sao unicos entre contas
    msg_ids_1 = {m.message_id for m in p1.messages}
    msg_ids_2 = {m.message_id for m in p2.messages}
    assert msg_ids_1.isdisjoint(msg_ids_2)


def test_gemini_no_account_no_prefix(tmp_path):
    """Sem account, conv_id nao tem prefixo."""
    path = _write_fixture(tmp_path, FIXTURE)
    parser = GeminiParser()
    parser.parse(path)
    assert parser.conversations[0].conversation_id == "abc123def456"
