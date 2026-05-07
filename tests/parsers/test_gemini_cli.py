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


# === Orphan handling (Slice B) ===

@pytest.fixture
def no_preservation_marking(monkeypatch):
    """Desabilita mark_cli_preservation pra tests de orphan handling.

    Orphan convs setam is_preserved_missing=True diretamente na ingestion;
    chats-backed convs ficam com o default False. Isolamos esse step pra nao
    depender do real ~/.gemini/tmp/ do usuario.
    """
    monkeypatch.setattr(
        "src.extractors.cli.preservation.mark_cli_preservation",
        lambda parser: 0,
    )

def _make_workspace(base: Path, workspace_name: str, sessions_with_chats: list[dict], orphan_logs: list[dict]) -> Path:
    """Helper: cria workspace estilo .gemini/tmp/<name>/ com chats/ e logs.json.

    sessions_with_chats: list of dicts with keys (sessionId, startTime, messages).
        Cada message dict precisa ter (type, content, timestamp).
    orphan_logs: list of {sessionId, messageId, type, message, timestamp}
        que serao adicionadas ao logs.json sem ter chats/ correspondente.
    """
    ws = base / workspace_name
    ws.mkdir(parents=True)
    chats = ws / "chats"
    chats.mkdir()
    for sess in sessions_with_chats:
        sf = chats / f"session-{sess['sessionId'][:8]}.json"
        sf.write_text(json.dumps({
            "sessionId": sess["sessionId"],
            "projectHash": sess.get("projectHash", "h"),
            "startTime": sess["startTime"],
            "lastUpdated": sess.get("lastUpdated", sess["startTime"]),
            "messages": sess["messages"],
            "kind": "main",
        }))
    # logs.json com prompts das sessions com chats (devem ser ignorados pelo parser)
    # + entries orphan (devem ser ingeridos como preserved)
    logs_payload = []
    for sess in sessions_with_chats:
        for i, m in enumerate(sess["messages"]):
            if m.get("type") == "user":
                # Para o logs.json, content vai como string (formato real do logs.json)
                content_parts = m.get("content", [])
                if isinstance(content_parts, list):
                    text = "\n\n".join(p.get("text", "") for p in content_parts if isinstance(p, dict))
                else:
                    text = str(content_parts)
                logs_payload.append({
                    "sessionId": sess["sessionId"],
                    "messageId": i,
                    "type": "user",
                    "message": text,
                    "timestamp": m.get("timestamp", sess["startTime"]),
                })
    logs_payload.extend(orphan_logs)
    (ws / "logs.json").write_text(json.dumps(logs_payload))
    (ws / ".project_root").write_text(f"/path/to/{workspace_name}")
    return ws


def test_orphan_session_in_logs_json_creates_preserved_conversation(tmp_path, no_preservation_marking):
    raw = tmp_path / "Gemini CLI"
    raw.mkdir()
    sessions = [{
        "sessionId": "aaaaaaaa-1111-2222-3333-444444444444",
        "startTime": "2026-04-01T10:00:00.000Z",
        "messages": [
            {"type": "user", "content": [{"text": "olá"}], "timestamp": "2026-04-01T10:00:00.000Z"},
            {"type": "gemini", "content": "olá!", "timestamp": "2026-04-01T10:00:01.000Z"},
        ],
    }]
    orphan_sid = "bbbbbbbb-5555-6666-7777-888888888888"
    orphan_logs = [
        {"sessionId": orphan_sid, "messageId": 0, "type": "user",
         "message": "primeira mensagem perdida", "timestamp": "2026-03-15T08:00:00.000Z"},
        {"sessionId": orphan_sid, "messageId": 1, "type": "user",
         "message": "segunda mensagem perdida", "timestamp": "2026-03-15T08:01:00.000Z"},
    ]
    _make_workspace(raw, "test-ws", sessions, orphan_logs)

    parser = GeminiCLIParser()
    parser.parse(raw)

    convs_by_id = {c.conversation_id: c for c in parser.conversations}
    assert "aaaaaaaa-1111-2222-3333-444444444444" in convs_by_id
    assert orphan_sid in convs_by_id

    chat_conv = convs_by_id["aaaaaaaa-1111-2222-3333-444444444444"]
    orphan_conv = convs_by_id[orphan_sid]
    assert chat_conv.is_preserved_missing is False
    assert orphan_conv.is_preserved_missing is True

    orphan_msgs = [m for m in parser.messages if m.conversation_id == orphan_sid]
    assert len(orphan_msgs) == 2
    assert all(m.role == "user" for m in orphan_msgs)
    contents = sorted(m.content for m in orphan_msgs)
    assert "primeira mensagem perdida" in contents
    assert "segunda mensagem perdida" in contents


def test_no_logs_json_works_as_before(tmp_path, no_preservation_marking):
    raw = tmp_path / "Gemini CLI"
    raw.mkdir()
    sessions = [{
        "sessionId": "cccccccc-1111-2222-3333-444444444444",
        "startTime": "2026-04-01T10:00:00.000Z",
        "messages": [
            {"type": "user", "content": [{"text": "hi"}], "timestamp": "2026-04-01T10:00:00.000Z"},
        ],
    }]
    ws = raw / "no-logs"
    ws.mkdir()
    chats = ws / "chats"
    chats.mkdir()
    for sess in sessions:
        sf = chats / f"session-{sess['sessionId'][:8]}.json"
        sf.write_text(json.dumps({
            "sessionId": sess["sessionId"],
            "startTime": sess["startTime"],
            "lastUpdated": sess["startTime"],
            "messages": sess["messages"],
            "kind": "main",
        }))
    (ws / ".project_root").write_text("/some/path")

    parser = GeminiCLIParser()
    parser.parse(raw)
    assert any(c.conversation_id == "cccccccc-1111-2222-3333-444444444444" for c in parser.conversations)


def test_logs_json_session_with_existing_chats_is_ignored(tmp_path, no_preservation_marking):
    raw = tmp_path / "Gemini CLI"
    raw.mkdir()
    sid = "dddddddd-1111-2222-3333-444444444444"
    sessions = [{
        "sessionId": sid,
        "startTime": "2026-04-01T10:00:00.000Z",
        "messages": [
            {"type": "user", "content": [{"text": "real"}], "timestamp": "2026-04-01T10:00:00.000Z"},
            {"type": "gemini", "content": "ack", "timestamp": "2026-04-01T10:00:01.000Z"},
        ],
    }]
    # logs.json tem entry pra essa session (via _make_workspace), mas como
    # chats/ existe, parser deve ignorar logs.json pra essa session.
    orphan_logs: list[dict] = []
    _make_workspace(raw, "ws", sessions, orphan_logs)

    parser = GeminiCLIParser()
    parser.parse(raw)
    msgs = [m for m in parser.messages if m.conversation_id == sid]
    user_msgs = [m for m in msgs if m.role == "user"]
    # Nao duplica: user message vem do chats/, nao do logs.json
    assert len(user_msgs) == 1
    assert user_msgs[0].content == "real"
