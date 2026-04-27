import json
import pytest
from pathlib import Path
from src.parsers.deepseek import DeepSeekParser


FIXTURE_SIMPLE = [
    {
        "id": "conv-001",
        "title": "Test conversation",
        "inserted_at": "2025-02-15T10:00:00.000+08:00",
        "updated_at": "2025-02-15T10:05:00.000+08:00",
        "mapping": {
            "root": {
                "id": "root",
                "parent": None,
                "children": ["1"],
                "message": None,
            },
            "1": {
                "id": "1",
                "parent": "root",
                "children": ["2"],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-02-15T10:00:00.000+08:00",
                    "fragments": [
                        {"type": "REQUEST", "content": "Hello, how are you?"}
                    ],
                },
            },
            "2": {
                "id": "2",
                "parent": "1",
                "children": [],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-02-15T10:00:05.000+08:00",
                    "fragments": [
                        {"type": "RESPONSE", "content": "I'm doing well!"}
                    ],
                },
            },
        },
    }
]

FIXTURE_WITH_THINKING = [
    {
        "id": "conv-002",
        "title": "Thinking conversation",
        "inserted_at": "2025-03-01T14:00:00.000+08:00",
        "updated_at": "2025-03-01T14:02:00.000+08:00",
        "mapping": {
            "root": {
                "id": "root",
                "parent": None,
                "children": ["1"],
                "message": None,
            },
            "1": {
                "id": "1",
                "parent": "root",
                "children": ["2"],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-03-01T14:00:00.000+08:00",
                    "fragments": [
                        {"type": "REQUEST", "content": "Explain quantum computing"}
                    ],
                },
            },
            "2": {
                "id": "2",
                "parent": "1",
                "children": [],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-03-01T14:00:10.000+08:00",
                    "fragments": [
                        {"type": "THINK", "content": "User wants explanation of QC..."},
                        {"type": "RESPONSE", "content": "Quantum computing uses qubits..."},
                    ],
                },
            },
        },
    }
]

FIXTURE_WITH_SEARCH = [
    {
        "id": "conv-003",
        "title": "Search conversation",
        "inserted_at": "2025-03-10T09:00:00.000+08:00",
        "updated_at": "2025-03-10T09:03:00.000+08:00",
        "mapping": {
            "root": {
                "id": "root",
                "parent": None,
                "children": ["1"],
                "message": None,
            },
            "1": {
                "id": "1",
                "parent": "root",
                "children": ["2"],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-03-10T09:00:00.000+08:00",
                    "fragments": [
                        {"type": "REQUEST", "content": "Search for accessibility research"}
                    ],
                },
            },
            "2": {
                "id": "2",
                "parent": "1",
                "children": [],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-03-10T09:00:15.000+08:00",
                    "fragments": [
                        {"type": "SEARCH", "content": "{\"results\": [{\"url\": \"https://example.com\"}]}"},
                        {"type": "RESPONSE", "content": "I found several studies..."},
                    ],
                },
            },
        },
    }
]

FIXTURE_WITH_BRANCH = [
    {
        "id": "conv-004",
        "title": "Branched conversation",
        "inserted_at": "2025-04-01T12:00:00.000+08:00",
        "updated_at": "2025-04-01T12:05:00.000+08:00",
        "mapping": {
            "root": {
                "id": "root",
                "parent": None,
                "children": ["1"],
                "message": None,
            },
            "1": {
                "id": "1",
                "parent": "root",
                "children": ["2", "3"],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-04-01T12:00:00.000+08:00",
                    "fragments": [
                        {"type": "REQUEST", "content": "Hello"}
                    ],
                },
            },
            "2": {
                "id": "2",
                "parent": "1",
                "children": [],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-04-01T12:00:05.000+08:00",
                    "fragments": [
                        {"type": "RESPONSE", "content": "First response (old branch)"}
                    ],
                },
            },
            "3": {
                "id": "3",
                "parent": "1",
                "children": [],
                "message": {
                    "files": [],
                    "model": "deepseek-chat",
                    "inserted_at": "2025-04-01T12:01:00.000+08:00",
                    "fragments": [
                        {"type": "RESPONSE", "content": "Second response (latest branch)"}
                    ],
                },
            },
        },
    }
]


def _write_fixture(tmp_path, data):
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(data))
    return p


def test_deepseek_simple_conversation(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_SIMPLE)
    parser = DeepSeekParser()
    parser.parse(path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2
    conv = parser.conversations[0]
    assert conv.conversation_id == "conv-001"
    assert conv.source == "deepseek"
    assert conv.title == "Test conversation"
    assert conv.model == "deepseek-chat"
    assert conv.message_count == 2
    assert conv.mode == "chat"
    user_msg = parser.messages[0]
    assert user_msg.role == "user"
    assert user_msg.content == "Hello, how are you?"
    assert user_msg.sequence == 1
    assert user_msg.content_types == "text"
    asst_msg = parser.messages[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.content == "I'm doing well!"
    assert asst_msg.sequence == 2
    assert asst_msg.thinking is None
    assert asst_msg.tool_results is None


def test_deepseek_thinking(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_WITH_THINKING)
    parser = DeepSeekParser()
    parser.parse(path)
    assert len(parser.messages) == 2
    asst_msg = parser.messages[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.content == "Quantum computing uses qubits..."
    assert asst_msg.thinking == "User wants explanation of QC..."


def test_deepseek_search(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_WITH_SEARCH)
    parser = DeepSeekParser()
    parser.parse(path)
    conv = parser.conversations[0]
    assert conv.mode == "search"
    asst_msg = parser.messages[1]
    assert asst_msg.tool_results is not None
    assert "example.com" in asst_msg.tool_results


def test_deepseek_branch_follows_last_child(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_WITH_BRANCH)
    parser = DeepSeekParser()
    parser.parse(path)
    assert len(parser.messages) == 2
    asst_msg = parser.messages[1]
    assert asst_msg.content == "Second response (latest branch)"


def test_deepseek_timestamps_utc(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_SIMPLE)
    parser = DeepSeekParser()
    parser.parse(path)
    conv = parser.conversations[0]
    # 10:00+08:00 = 02:00 UTC = 23:00 BRT do dia anterior
    assert conv.created_at.hour == 23


def test_deepseek_duplicate_fragments_concatenated(tmp_path):
    """Multiplos RESPONSE fragments sao concatenados, nao sobrescritos."""
    fixture = [
        {
            "id": "conv-dup",
            "title": "Duplicate fragments",
            "inserted_at": "2025-03-15T10:00:00.000+08:00",
            "updated_at": "2025-03-15T10:01:00.000+08:00",
            "mapping": {
                "root": {
                    "id": "root",
                    "parent": None,
                    "children": ["1"],
                    "message": None,
                },
                "1": {
                    "id": "1",
                    "parent": "root",
                    "children": [],
                    "message": {
                        "files": [],
                        "model": "deepseek-chat",
                        "inserted_at": "2025-03-15T10:00:00.000+08:00",
                        "fragments": [
                            {"type": "RESPONSE", "content": "Parte 1 da resposta."},
                            {"type": "RESPONSE", "content": "Parte 2 da resposta."},
                        ],
                    },
                },
            },
        }
    ]
    path = _write_fixture(tmp_path, fixture)
    parser = DeepSeekParser()
    parser.parse(path)

    assert len(parser.messages) == 1
    msg = parser.messages[0]
    assert "Parte 1" in msg.content
    assert "Parte 2" in msg.content
