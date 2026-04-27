import json
import pytest
import pandas as pd
from pathlib import Path
from src.parsers.qwen import QwenParser


FIXTURE = {
    "success": True,
    "request_id": "req-001",
    "data": [
        {
            "id": "conv-q1",
            "user_id": "user-001",
            "title": "Qwen test chat",
            "chat": {
                "history": {
                    "messages": {
                        "msg-root": {
                            "id": "msg-root",
                            "role": "user",
                            "content": "",
                            "model": "qwen-max",
                            "parentId": None,
                            "childrenIds": ["msg-1"],
                            "content_list": [
                                {
                                    "content": "What is Python?",
                                    "phase": "user_input",
                                    "status": "finished",
                                    "role": "user",
                                    "timestamp": 1706500000,
                                }
                            ],
                        },
                        "msg-1": {
                            "id": "msg-1",
                            "role": "assistant",
                            "content": "",
                            "model": "qwen-max",
                            "parentId": "msg-root",
                            "childrenIds": [],
                            "content_list": [
                                {
                                    "content": "Python is a programming language...",
                                    "phase": "response",
                                    "status": "finished",
                                    "role": "assistant",
                                    "timestamp": 1706500010,
                                }
                            ],
                        },
                    }
                }
            },
            "updated_at": 1706500010,
            "created_at": 1706500000,
        }
    ],
}

FIXTURE_WITH_FILES = {
    "success": True,
    "request_id": "req-002",
    "data": [
        {
            "id": "conv-q2",
            "user_id": "user-001",
            "title": "File upload chat",
            "chat": {
                "history": {
                    "messages": {
                        "msg-root": {
                            "id": "msg-root",
                            "role": "user",
                            "content": "",
                            "model": "qwen-max",
                            "parentId": None,
                            "childrenIds": ["msg-1"],
                            "content_list": [
                                {
                                    "content": "Analyze this",
                                    "phase": "user_input",
                                    "status": "finished",
                                    "role": "user",
                                    "timestamp": 1706600000,
                                }
                            ],
                            "files": [{"name": "data.csv", "type": "text/csv"}],
                        },
                        "msg-1": {
                            "id": "msg-1",
                            "role": "assistant",
                            "content": "",
                            "model": "qwen-max",
                            "parentId": "msg-root",
                            "childrenIds": [],
                            "content_list": [
                                {
                                    "content": "The CSV contains...",
                                    "phase": "response",
                                    "status": "finished",
                                    "role": "assistant",
                                    "timestamp": 1706600010,
                                }
                            ],
                        },
                    }
                }
            },
            "updated_at": 1706600010,
            "created_at": 1706600000,
        }
    ],
}


def _write_fixture(tmp_path, data):
    p = tmp_path / "export.json"
    p.write_text(json.dumps(data))
    return p


def test_qwen_simple(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = QwenParser()
    parser.parse(path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2
    conv = parser.conversations[0]
    assert conv.conversation_id == "conv-q1"
    assert conv.source == "qwen"
    assert conv.title == "Qwen test chat"
    assert conv.model == "qwen-max"
    assert conv.mode == "chat"
    user_msg = parser.messages[0]
    assert user_msg.role == "user"
    assert user_msg.content == "What is Python?"
    assert user_msg.sequence == 1
    asst_msg = parser.messages[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.content == "Python is a programming language..."


def test_qwen_timestamps_from_unix(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = QwenParser()
    parser.parse(path)
    conv = parser.conversations[0]
    # epoch 1706500000 = 2024-01-29 03:46:40 UTC → 00:46:40 BRT
    assert conv.created_at == pd.Timestamp("2024-01-29 00:46:40")


def test_qwen_files_to_attachments(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_WITH_FILES)
    parser = QwenParser()
    parser.parse(path)
    user_msg = parser.messages[0]
    assert user_msg.attachment_names is not None
    assert "data.csv" in user_msg.attachment_names
    assert "document" in user_msg.content_types


def test_qwen_multiple_roots_warns(tmp_path, caplog):
    """Conversa com 2 msgs parentId=None deve logar warning."""
    data = {"data": [{"id": "c1", "title": "Multi root",
        "created_at": 1700000000, "updated_at": 1700000000,
        "chat": {"history": {"messages": {
            "m1": {"id": "m1", "parentId": None, "role": "user",
                   "content": "First root", "childrenIds": []},
            "m2": {"id": "m2", "parentId": None, "role": "user",
                   "content": "Second root", "childrenIds": []},
        }}}}]}
    path = _write_fixture(tmp_path, data)
    import logging
    with caplog.at_level(logging.WARNING):
        parser = QwenParser()
        parser.parse(path)
    assert "2 roots" in caplog.text
