# tests/parsers/test_gemini_cli.py
import json
import pytest
import pandas as pd
from pathlib import Path
from src.parsers.gemini_cli import GeminiCLIParser

FIXTURE_SESSION = {
    "sessionId": "e2a78e15-1111-2222-3333-444455556666",
    "projectHash": "abc123",
    "startTime": "2026-03-27T03:19:00.376Z",
    "lastUpdated": "2026-03-27T15:52:57.047Z",
    "kind": "main",
    "messages": [
        {
            "id": "msg-user-1",
            "timestamp": "2026-03-27T03:19:00.376Z",
            "type": "user",
            "content": [{"text": "Analise esse projeto."}],
        },
        {
            "id": "msg-gemini-1",
            "timestamp": "2026-03-27T03:19:09.273Z",
            "type": "gemini",
            "content": "Vou analisar o projeto.",
            "thoughts": [
                {"subject": "Reviewing", "description": "Looking at structure", "timestamp": "2026-03-27T03:19:05Z"}
            ],
            "tokens": {"input": 7577, "output": 81, "cached": 0, "thoughts": 209, "tool": 0, "total": 7867},
            "model": "gemini-3-flash-preview",
            "toolCalls": [
                {
                    "id": "read_file_001",
                    "name": "read_file",
                    "args": {"file_path": "README.md"},
                    "result": [{"functionResponse": {"id": "read_file_001", "name": "read_file", "response": {"output": "# Project"}}}],
                    "status": "success",
                    "timestamp": "2026-03-27T03:19:09.328Z",
                }
            ],
        },
        {
            "id": "msg-info-1",
            "timestamp": "2026-03-27T03:20:00Z",
            "type": "info",
            "content": "Update successful",
        },
    ],
}


def _setup_gemini_dir(tmp_path, sessions=None, project_root=None):
    """Cria estrutura de diretorios do Gemini CLI."""
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    if project_root:
        (project_dir / ".project_root").write_text(project_root)
    chats_dir = project_dir / "chats"
    chats_dir.mkdir()
    for i, session in enumerate(sessions or [FIXTURE_SESSION]):
        (chats_dir / f"session-2026-03-27T03-19-{i:08x}.json").write_text(
            json.dumps(session, ensure_ascii=False)
        )
    return tmp_path


def test_gemini_cli_basic(tmp_path):
    path = _setup_gemini_dir(tmp_path, project_root="/Users/test/project")
    parser = GeminiCLIParser()
    parser.parse(path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2  # user + gemini (info ignorado)
    assert len(parser.events) == 1   # 1 tool call
    conv = parser.conversations[0]
    assert conv.source == "gemini_cli"
    assert conv.mode == "cli"
    assert conv.project == "/Users/test/project"
    assert conv.message_count == 2


def test_gemini_cli_messages(tmp_path):
    path = _setup_gemini_dir(tmp_path)
    parser = GeminiCLIParser()
    parser.parse(path)
    user_msg = parser.messages[0]
    assert user_msg.role == "user"
    assert user_msg.content == "Analise esse projeto."
    asst_msg = parser.messages[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.model == "gemini-3-flash-preview"
    assert asst_msg.token_count == 7867
    assert "Looking at structure" in asst_msg.thinking


def test_gemini_cli_tool_events(tmp_path):
    path = _setup_gemini_dir(tmp_path)
    parser = GeminiCLIParser()
    parser.parse(path)
    evt = parser.events[0]
    assert evt.tool_name == "read_file"
    assert evt.file_path == "README.md"
    assert evt.success is True
    assert evt.event_type == "tool_call"


def test_gemini_cli_parse_files_processes_only_given_files(tmp_path):
    """parse_files deve processar apenas a lista de arquivos passada, inferindo project do path."""
    sess_a = dict(FIXTURE_SESSION)
    sess_a["sessionId"] = "sess-aaa"
    sess_b = dict(FIXTURE_SESSION)
    sess_b["sessionId"] = "sess-bbb"

    path = _setup_gemini_dir(tmp_path, sessions=[sess_a, sess_b], project_root="/Users/test/project")

    chats_dir = path / "my-project" / "chats"
    files = sorted(chats_dir.glob("session-*.json"))
    assert len(files) == 2

    parser = GeminiCLIParser()
    parser.parse_files([files[0]])

    assert len(parser.conversations) == 1
    assert parser.conversations[0].conversation_id == "sess-aaa"
    assert parser.conversations[0].project == "/Users/test/project"  # inferido via .project_root


def test_gemini_cli_empty_session(tmp_path):
    empty = {"sessionId": "empty-1", "startTime": "2026-01-01T00:00:00Z",
             "lastUpdated": "2026-01-01T00:00:00Z", "messages": [], "kind": "main"}
    path = _setup_gemini_dir(tmp_path, sessions=[empty])
    parser = GeminiCLIParser()
    parser.parse(path)
    assert len(parser.conversations) == 0
    assert len(parser.messages) == 0


def test_gemini_cli_hash_project(tmp_path):
    """Projeto sem .project_root usa nome da pasta."""
    path = _setup_gemini_dir(tmp_path)  # sem project_root
    parser = GeminiCLIParser()
    parser.parse(path)
    assert parser.conversations[0].project == "my-project"
