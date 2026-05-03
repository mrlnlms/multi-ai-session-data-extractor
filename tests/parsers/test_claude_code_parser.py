# tests/parsers/test_claude_code.py
import json
import pytest
import pandas as pd
from pathlib import Path
from src.parsers.claude_code import ClaudeCodeParser

FIXTURE_LINES = [
    {"type": "user", "uuid": "u1", "timestamp": "2026-03-02T16:04:29.025Z",
     "sessionId": "session-001", "cwd": "/Users/test/project",
     "version": "2.1.87", "gitBranch": "main", "slug": "eventual-forging-sunrise",
     "isSidechain": False, "parentUuid": None, "userType": "external",
     "message": {"role": "user", "content": [{"type": "text", "text": "Mostra os testes."}]}},

    {"type": "assistant", "uuid": "a1", "timestamp": "2026-03-02T16:04:40.684Z",
     "sessionId": "session-001", "cwd": "/Users/test/project",
     "version": "2.1.87", "gitBranch": "main", "slug": "eventual-forging-sunrise",
     "isSidechain": False, "parentUuid": "u1", "userType": "external",
     "requestId": "req_001",
     "message": {
         "model": "claude-opus-4-6", "id": "msg_001", "type": "message",
         "role": "assistant",
         "content": [
             {"type": "thinking", "thinking": "I should read the test files.", "signature": "abc123"},
             {"type": "text", "text": "Vou ler os arquivos de teste."},
             {"type": "tool_use", "id": "toolu_001", "name": "Read",
              "input": {"file_path": "tests/test_main.py"}},
         ],
         "stop_reason": "tool_use",
         "usage": {"input_tokens": 100, "output_tokens": 50,
                   "cache_creation_input_tokens": 0, "cache_read_input_tokens": 80},
     }},

    # User msg com tool_result (continuacao, nao gera Message)
    {"type": "user", "uuid": "u2", "timestamp": "2026-03-02T16:04:45Z",
     "sessionId": "session-001", "cwd": "/Users/test/project",
     "version": "2.1.87", "gitBranch": "main", "slug": "eventual-forging-sunrise",
     "isSidechain": False, "parentUuid": "a1", "userType": "external",
     "sourceToolAssistantUUID": "a1",
     "message": {"role": "user", "content": [
         {"tool_use_id": "toolu_001", "type": "tool_result", "content": "def test_main(): pass"}
     ]}},

    # System event
    {"type": "system", "uuid": "s1", "timestamp": "2026-03-02T16:05:00Z",
     "sessionId": "session-001", "cwd": "/Users/test/project",
     "subtype": "turn_duration", "durationMs": 31000,
     "isSidechain": False, "version": "2.1.87", "gitBranch": "main",
     "slug": "eventual-forging-sunrise", "parentUuid": "a1", "userType": "external"},
]


def _write_session(tmp_path, lines=None, project_name="test-project"):
    """Cria estrutura de diretorios do Claude Code."""
    project_dir = tmp_path / f"-Users-test-Desktop-{project_name}"
    project_dir.mkdir()
    session_file = project_dir / "session-001.jsonl"
    content = "\n".join(json.dumps(line) for line in (lines or FIXTURE_LINES))
    session_file.write_text(content)
    return tmp_path


def test_claude_code_basic(tmp_path):
    path = _write_session(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2  # user text + assistant (tool_result nao gera msg)
    assert len(parser.events) == 1   # 1 tool_use
    conv = parser.conversations[0]
    assert conv.source == "claude_code"
    assert conv.mode == "cli"
    assert conv.project == "/Users/test/project"


def test_claude_code_messages(tmp_path):
    path = _write_session(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    user_msg = parser.messages[0]
    assert user_msg.role == "user"
    assert user_msg.content == "Mostra os testes."
    asst_msg = parser.messages[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.model == "claude-opus-4-6"
    assert asst_msg.content == "Vou ler os arquivos de teste."
    assert "I should read the test files" in asst_msg.thinking
    assert asst_msg.token_count == 150  # input + output


def test_claude_code_tool_events(tmp_path):
    path = _write_session(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    evt = parser.events[0]
    assert evt.tool_name == "Read"
    assert evt.file_path == "tests/test_main.py"
    assert evt.event_type == "tool_call"


def test_claude_code_tool_result_links(tmp_path):
    path = _write_session(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    evt = parser.events[0]
    # tool_result do user seguinte deve ser capturado
    assert evt.success is True  # tool_result sem is_error = success


def test_claude_code_sidechain_ignored(tmp_path):
    """Eventos com isSidechain=true sao ignorados."""
    lines = list(FIXTURE_LINES)
    lines[0] = {**lines[0], "isSidechain": True}
    path = _write_session(tmp_path, lines)
    parser = ClaudeCodeParser()
    parser.parse(path)
    # Primeiro user msg ignorado, so assistant (que tem isSidechain=False) e processado
    assert len(parser.messages) == 1  # so o assistant


def test_claude_code_slug_as_title(tmp_path):
    path = _write_session(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    assert parser.conversations[0].title == "eventual-forging-sunrise"


def test_claude_code_empty_session(tmp_path):
    lines = [{"type": "system", "uuid": "s1", "timestamp": "2026-01-01T00:00:00Z",
              "sessionId": "empty-1", "cwd": "/test", "subtype": "turn_duration",
              "durationMs": 0, "isSidechain": False, "version": "2.1.87",
              "gitBranch": "main", "parentUuid": None, "userType": "external"}]
    path = _write_session(tmp_path, lines)
    parser = ClaudeCodeParser()
    parser.parse(path)
    assert len(parser.conversations) == 0


# --- Subagent tests ---

SUBAGENT_LINES = [
    {"type": "user", "uuid": "su1", "timestamp": "2026-03-02T16:05:00Z",
     "sessionId": "session-001", "cwd": "/Users/test/project",
     "version": "2.1.87", "gitBranch": "main",
     "isSidechain": True, "parentUuid": None, "userType": "external",
     "agentId": "abc123", "promptId": "prompt-001",
     "message": {"role": "user", "content": [{"type": "text", "text": "Implement the parser."}]}},

    {"type": "assistant", "uuid": "sa1", "timestamp": "2026-03-02T16:05:10Z",
     "sessionId": "session-001", "cwd": "/Users/test/project",
     "version": "2.1.87", "gitBranch": "main",
     "isSidechain": True, "parentUuid": "su1", "userType": "external",
     "requestId": "req_sub_001",
     "message": {
         "model": "claude-haiku-4-5-20251001", "id": "msg_sub_001", "type": "message",
         "role": "assistant",
         "content": [
             {"type": "text", "text": "Done. Parser implemented."},
         ],
         "stop_reason": "end_turn",
         "usage": {"input_tokens": 200, "output_tokens": 30,
                   "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
     }},
]


def _write_session_with_subagent(tmp_path):
    """Cria sessao principal + subagent no diretorio correto."""
    project_dir = tmp_path / "-Users-test-Desktop-test-project"
    project_dir.mkdir()
    # Sessao principal
    session_file = project_dir / "session-001.jsonl"
    session_file.write_text("\n".join(json.dumps(l) for l in FIXTURE_LINES))
    # Subagent
    sub_dir = project_dir / "session-001" / "subagents"
    sub_dir.mkdir(parents=True)
    sub_file = sub_dir / "agent-abc123.jsonl"
    sub_file.write_text("\n".join(json.dumps(l) for l in SUBAGENT_LINES))
    return tmp_path


def test_subagent_parsed(tmp_path):
    path = _write_session_with_subagent(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    assert len(parser.conversations) == 2  # 1 principal + 1 subagent


def test_subagent_interaction_type(tmp_path):
    path = _write_session_with_subagent(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    main = [c for c in parser.conversations if c.interaction_type == "human_ai"]
    subs = [c for c in parser.conversations if c.interaction_type == "ai_ai"]
    assert len(main) == 1
    assert len(subs) == 1
    assert subs[0].parent_session_id == "session-001"


def test_subagent_messages(tmp_path):
    path = _write_session_with_subagent(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    # Subagent msgs tem conversation_id = filename stem (agent-abc123)
    sub_msgs = [m for m in parser.messages if m.conversation_id == "agent-abc123"]
    assert len(sub_msgs) == 2  # user + assistant
    asst = [m for m in sub_msgs if m.role == "assistant"][0]
    assert asst.content == "Done. Parser implemented."
    assert asst.model == "claude-haiku-4-5-20251001"


def test_subagent_model_differs(tmp_path):
    """Subagents tipicamente usam modelo diferente (haiku vs opus)."""
    path = _write_session_with_subagent(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    models = {m.model for m in parser.messages if m.model}
    assert "claude-opus-4-6" in models        # sessao principal
    assert "claude-haiku-4-5-20251001" in models  # subagent


def test_main_session_interaction_type_default(tmp_path):
    """Sessoes principais tem interaction_type=human_ai por padrao."""
    path = _write_session(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)
    assert parser.conversations[0].interaction_type == "human_ai"
    assert parser.conversations[0].parent_session_id is None


def test_claude_code_parse_files_handles_root_and_subagent(tmp_path):
    """parse_files detecta root vs subagent pelo path e gera conversas corretas."""
    _write_session_with_subagent(tmp_path)
    project_dir = tmp_path / "-Users-test-Desktop-test-project"
    root_file = project_dir / "session-001.jsonl"
    sub_file = project_dir / "session-001" / "subagents" / "agent-abc123.jsonl"

    parser = ClaudeCodeParser()
    parser.parse_files([root_file, sub_file])

    convs = {c.conversation_id: c for c in parser.conversations}
    assert "session-001" in convs
    assert "agent-abc123" in convs
    assert convs["session-001"].interaction_type == "human_ai"
    assert convs["session-001"].parent_session_id is None
    assert convs["agent-abc123"].interaction_type == "ai_ai"
    assert convs["agent-abc123"].parent_session_id == "session-001"


def test_claude_code_parse_files_only_root(tmp_path):
    """parse_files com só root (sem subagent) processa só o root."""
    _write_session_with_subagent(tmp_path)
    project_dir = tmp_path / "-Users-test-Desktop-test-project"
    root_file = project_dir / "session-001.jsonl"

    parser = ClaudeCodeParser()
    parser.parse_files([root_file])

    # Só 1 conversa (root), subagent não processado
    assert len(parser.conversations) == 1
    assert parser.conversations[0].conversation_id == "session-001"
    assert parser.conversations[0].interaction_type == "human_ai"


# --- v3-specific tests ---

def test_branches_one_per_conversation(tmp_path):
    """v3: 1 Branch <conv>_main por Conversation (Claude Code nao tem fork)."""
    path = _write_session_with_subagent(tmp_path)
    parser = ClaudeCodeParser()
    parser.parse(path)

    assert len(parser.branches) == len(parser.conversations) == 2
    branches_by_conv = {b.conversation_id: b for b in parser.branches}
    for conv in parser.conversations:
        b = branches_by_conv[conv.conversation_id]
        assert b.branch_id == f"{conv.conversation_id}_main"
        assert b.is_active is True
        assert b.source == "claude_code"
        assert b.parent_branch_id is None


def test_write_parquets(tmp_path):
    """v3: write_parquets gera 4 arquivos canonicos com naming claude_code_*."""
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    raw_path = _write_session(raw_root)
    out_dir = tmp_path / "processed"
    parser = ClaudeCodeParser()
    parser.parse(raw_path)
    stats = parser.write_parquets(out_dir)

    expected = {
        "claude_code_conversations.parquet",
        "claude_code_messages.parquet",
        "claude_code_tool_events.parquet",
        "claude_code_branches.parquet",
    }
    assert {p.name for p in out_dir.glob("*.parquet")} == expected
    assert stats["conversations"] == 1
    assert stats["messages"] == 2
    assert stats["tool_events"] == 1
    assert stats["branches"] == 1


def test_idempotent_parquets(tmp_path):
    """Rodar parser+write 2x produz mesmo bytes."""
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    raw_path = _write_session(raw_root)
    out_dir = tmp_path / "processed"

    p1 = ClaudeCodeParser()
    p1.parse(raw_path)
    p1.write_parquets(out_dir)
    sizes_first = {p.name: p.stat().st_size for p in out_dir.glob("*.parquet")}

    p2 = ClaudeCodeParser()
    p2.parse(raw_path)
    p2.write_parquets(out_dir)
    sizes_second = {p.name: p.stat().st_size for p in out_dir.glob("*.parquet")}

    assert sizes_first == sizes_second


def test_user_content_as_string(tmp_path):
    """Regression test: content como string (nao lista) era descartado.

    Bug pre-a391e5d perdia 10.7k msgs quando content vinha como str direto
    em vez de list of blocks.
    """
    lines = [
        {"type": "user", "uuid": "u1", "timestamp": "2026-03-02T16:04:29Z",
         "sessionId": "session-str", "cwd": "/test", "version": "2.1",
         "isSidechain": False, "parentUuid": None, "userType": "external",
         "message": {"role": "user", "content": "Plain string content"}},
        {"type": "assistant", "uuid": "a1", "timestamp": "2026-03-02T16:04:30Z",
         "sessionId": "session-str", "cwd": "/test",
         "isSidechain": False, "parentUuid": "u1", "userType": "external",
         "message": {
             "model": "claude-x", "content": [{"type": "text", "text": "ok"}],
             "usage": {"input_tokens": 1, "output_tokens": 1},
         }},
    ]
    project_dir = tmp_path / "-Users-test"
    project_dir.mkdir()
    (project_dir / "session-str.jsonl").write_text(
        "\n".join(json.dumps(l) for l in lines)
    )

    parser = ClaudeCodeParser()
    parser.parse(tmp_path)

    user_msgs = [m for m in parser.messages if m.role == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0].content == "Plain string content"
