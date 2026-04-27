import json
import pytest
from pathlib import Path
from src.parsers.claude_ai import ClaudeAIParser
import pandas as pd


FIXTURE = [
    {
        "uuid": "conv-claude1",
        "name": "Data analysis chat",
        "summary": "",
        "created_at": "2025-06-20T09:00:00.000000Z",
        "updated_at": "2025-06-20T09:45:00.000000Z",
        "chat_messages": [
            {
                "uuid": "msg-c1",
                "sender": "human",
                "text": "",
                "content": [
                    {"type": "text", "text": "Analyze this CSV for me"}
                ],
                "created_at": "2025-06-20T09:00:00.000000Z",
                "updated_at": "2025-06-20T09:00:00.000000Z",
                "attachments": [],
                "files": [
                    {"file_name": "dados.csv"}
                ],
            },
            {
                "uuid": "msg-c2",
                "sender": "assistant",
                "text": "",
                "content": [
                    {"type": "text", "text": "The dataset contains 1.2k records..."},
                ],
                "created_at": "2025-06-20T09:01:00.000000Z",
                "updated_at": "2025-06-20T09:01:00.000000Z",
                "attachments": [],
                "files": [],
            },
        ],
    },
    {
        "uuid": "conv-claude2",
        "name": "",
        "summary": "",
        "created_at": "2025-07-10T14:00:00.000000Z",
        "updated_at": "2025-07-10T14:10:00.000000Z",
        "chat_messages": [
            {
                "uuid": "msg-c3",
                "sender": "human",
                "text": "",
                "content": [
                    {"type": "text", "text": "Look at this image"},
                    {"type": "image", "source": {"type": "base64"}},
                ],
                "created_at": "2025-07-10T14:00:00.000000Z",
                "updated_at": "2025-07-10T14:00:00.000000Z",
                "attachments": [{"file_name": "screenshot.png"}],
                "files": [],
            },
            {
                "uuid": "msg-c4",
                "sender": "assistant",
                "text": "",
                "content": [
                    {"type": "text", "text": "I can see a chart showing..."},
                ],
                "created_at": "2025-07-10T14:01:00.000000Z",
                "updated_at": "2025-07-10T14:01:00.000000Z",
                "attachments": [],
                "files": [],
            },
        ],
    },
]


def _write_fixture(tmp_path, data):
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(data))
    return p


def test_claude_ai_basic(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ClaudeAIParser()
    parser.parse(path)
    assert len(parser.conversations) == 2
    assert len(parser.messages) == 4
    conv = parser.conversations[0]
    assert conv.conversation_id == "conv-claude1"
    assert conv.source == "claude_ai"
    assert conv.title == "Data analysis chat"
    assert conv.mode == "chat"
    assert conv.message_count == 2


def test_claude_ai_empty_title_becomes_none(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ClaudeAIParser()
    parser.parse(path)
    conv = parser.conversations[1]
    assert conv.title is None


def test_claude_ai_role_mapping(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ClaudeAIParser()
    parser.parse(path)
    assert parser.messages[0].role == "user"
    assert parser.messages[1].role == "assistant"


def test_claude_ai_content_blocks_concatenated(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ClaudeAIParser()
    parser.parse(path)
    msg = parser.messages[0]
    assert msg.content == "Analyze this CSV for me"


def test_claude_ai_content_types_with_image(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ClaudeAIParser()
    parser.parse(path)
    msg = parser.messages[2]  # human with text + image
    assert "text" in msg.content_types
    assert "image" in msg.content_types


def test_claude_ai_files_to_attachment_names(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ClaudeAIParser()
    parser.parse(path)
    msg = parser.messages[0]
    assert msg.attachment_names is not None
    assert "dados.csv" in msg.attachment_names
    msg2 = parser.messages[2]
    assert msg2.attachment_names is not None
    assert "screenshot.png" in msg2.attachment_names


def test_claude_ai_timestamps(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ClaudeAIParser()
    parser.parse(path)
    conv = parser.conversations[0]
    # 09:00 UTC → 06:00 BRT
    assert conv.created_at == pd.Timestamp("2025-06-20 06:00:00")


PROJECTS_FIXTURE = [
    {
        "uuid": "proj-1",
        "name": "Survey Quality",
        "description": "Analise qualitativa de surveys",
        "is_private": True,
        "is_starter_project": False,
        "prompt_template": "Voce e um especialista em surveys.",
        "created_at": "2025-08-01T10:00:00.000000Z",
        "updated_at": "2025-09-15T14:00:00.000000Z",
        "creator": {"uuid": "user-1", "full_name": "Marlon"},
        "docs": [
            {"uuid": "doc-1", "filename": "guia.md", "content": "conteudo..."},
            {"uuid": "doc-2", "filename": "template.txt", "content": "template..."},
        ],
    },
    {
        "uuid": "proj-2",
        "name": "QDA",
        "description": "",
        "is_private": False,
        "is_starter_project": False,
        "prompt_template": "",
        "created_at": "2025-10-01T08:00:00.000000Z",
        "updated_at": "2025-10-01T08:00:00.000000Z",
        "creator": {"uuid": "user-1", "full_name": "Marlon"},
        "docs": [],
    },
]


def test_parse_projects_basic(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(PROJECTS_FIXTURE))

    parser = ClaudeAIParser()
    parser.parse_projects(path)

    assert len(parser.projects) == 2
    p = parser.projects[0]
    assert p.project_id == "proj-1"
    assert p.name == "Survey Quality"
    assert p.doc_count == 2
    assert "guia.md" in p.doc_names


def test_parse_projects_empty_docs(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(PROJECTS_FIXTURE))

    parser = ClaudeAIParser()
    parser.parse_projects(path)

    p = parser.projects[1]
    assert p.doc_count == 0
    assert json.loads(p.doc_names) == []


def test_projects_df_columns(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(PROJECTS_FIXTURE))

    parser = ClaudeAIParser()
    parser.parse_projects(path)

    df = parser.projects_df()
    assert list(df.columns) == [
        "project_id", "name", "description", "is_private",
        "prompt_template", "created_at", "updated_at", "doc_count", "doc_names",
    ]
    assert len(df) == 2
