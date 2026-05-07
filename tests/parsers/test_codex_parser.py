# tests/parsers/test_codex.py
import json
import pytest
import pandas as pd
from pathlib import Path
from src.parsers.codex import CodexParser

# Fixture: sessao minima com user msg, agent msg, function call, exec_command_end
FIXTURE_LINES = [
    {"timestamp": "2026-03-02T12:34:48.179Z", "type": "session_meta", "payload": {
        "id": "019cae8b-1111-2222-3333-444455556666",
        "timestamp": "2026-03-02T12:34:48.128Z",
        "cwd": "/Users/test/project",
        "originator": "codex_cli_rs",
        "cli_version": "0.106.0",
        "model_provider": "openai",
        "git": {"commit_hash": "abc123", "branch": "main"},
    }},
    {"timestamp": "2026-03-02T12:35:00Z", "type": "turn_context", "payload": {
        "model": "gpt-5.2-codex",
        "cwd": "/Users/test/project",
    }},
    {"timestamp": "2026-03-02T12:35:39.708Z", "type": "event_msg", "payload": {
        "type": "user_message",
        "message": "Liste os arquivos do projeto.",
        "images": [],
    }},
    {"timestamp": "2026-03-02T12:35:45.966Z", "type": "event_msg", "payload": {
        "type": "agent_reasoning",
        "text": "Planning to list files in the project directory.",
    }},
    {"timestamp": "2026-03-02T12:35:50Z", "type": "response_item", "payload": {
        "type": "function_call",
        "name": "exec_command",
        "arguments": '{"cmd": "ls -la", "yield_time_ms": 1000}',
        "call_id": "call_001",
    }},
    {"timestamp": "2026-03-02T12:35:56.253Z", "type": "response_item", "payload": {
        "type": "function_call_output",
        "call_id": "call_001",
        "output": "Wall time: 0.05 seconds\nProcess exited with code 0\nOutput:\nREADME.md\nsrc/",
    }},
    {"timestamp": "2026-03-02T12:35:57Z", "type": "event_msg", "payload": {
        "type": "exec_command_end",
        "command": "ls -la",
        "cwd": "/Users/test/project",
        "exit_code": 0,
        "stdout": "README.md\nsrc/",
        "stderr": "",
        "duration": {"secs": 0, "nanos": 51100000},
        "call_id": "call_001",
    }},
    {"timestamp": "2026-03-02T12:36:00Z", "type": "event_msg", "payload": {
        "type": "agent_message",
        "message": "O projeto tem um README.md e uma pasta src/.",
    }},
]


def _write_session(tmp_path, lines=None):
    """Cria estrutura de diretorios do Codex com uma sessao."""
    session_dir = tmp_path / "2026" / "03" / "02"
    session_dir.mkdir(parents=True)
    p = session_dir / "rollout-2026-03-02T12-34-48-019cae8b.jsonl"
    content = "\n".join(json.dumps(line) for line in (lines or FIXTURE_LINES))
    p.write_text(content)
    return tmp_path


def test_codex_basic(tmp_path):
    path = _write_session(tmp_path)
    parser = CodexParser()
    parser.parse(path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2  # user + agent_message
    assert len(parser.events) == 1   # 1 function_call
    conv = parser.conversations[0]
    assert conv.source == "codex"
    assert conv.mode == "cli"
    assert conv.project == "/Users/test/project"
    assert conv.model == "gpt-5.2-codex"


def test_codex_parse_files_processes_only_given_files(tmp_path):
    """parse_files deve processar apenas a lista de arquivos passada."""
    # Cria 2 sessões em paths diferentes
    session_dir = tmp_path / "2026" / "03" / "02"
    session_dir.mkdir(parents=True)

    lines_1 = [dict(line) for line in FIXTURE_LINES]
    lines_1[0] = {**lines_1[0], "payload": {**lines_1[0]["payload"], "id": "sess-aaa"}}
    f1 = session_dir / "rollout-2026-03-02T12-34-48-sess-aaa.jsonl"
    f1.write_text("\n".join(json.dumps(l) for l in lines_1))

    lines_2 = [dict(line) for line in FIXTURE_LINES]
    lines_2[0] = {**lines_2[0], "payload": {**lines_2[0]["payload"], "id": "sess-bbb"}}
    f2 = session_dir / "rollout-2026-03-02T13-00-00-sess-bbb.jsonl"
    f2.write_text("\n".join(json.dumps(l) for l in lines_2))

    parser = CodexParser()
    parser.parse_files([f1])

    assert len(parser.conversations) == 1
    assert parser.conversations[0].conversation_id == "sess-aaa"


def test_codex_messages(tmp_path):
    path = _write_session(tmp_path)
    parser = CodexParser()
    parser.parse(path)
    user_msg = parser.messages[0]
    assert user_msg.role == "user"
    assert user_msg.content == "Liste os arquivos do projeto."
    asst_msg = parser.messages[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.content == "O projeto tem um README.md e uma pasta src/."
    assert "Planning to list files" in asst_msg.thinking


def test_codex_tool_events(tmp_path):
    path = _write_session(tmp_path)
    parser = CodexParser()
    parser.parse(path)
    evt = parser.events[0]
    assert evt.tool_name == "exec_command"
    assert evt.command == "ls -la"
    assert evt.success is True
    assert evt.duration_ms == 51  # 0 secs + 51100000 nanos


def test_codex_empty_session(tmp_path):
    lines = [FIXTURE_LINES[0]]  # so session_meta, sem msgs
    path = _write_session(tmp_path, lines)
    parser = CodexParser()
    parser.parse(path)
    assert len(parser.conversations) == 0


def test_codex_multiple_sessions(tmp_path):
    _write_session(tmp_path)
    # Adicionar segunda sessao em outro dia
    day2 = tmp_path / "2026" / "03" / "03"
    day2.mkdir(parents=True)
    lines2 = list(FIXTURE_LINES)
    lines2[0] = {**lines2[0], "payload": {**lines2[0]["payload"], "id": "019cae8b-2222-3333-4444-555566667777"}}
    (day2 / "rollout-2026-03-03T10-00-00-019cae8b.jsonl").write_text(
        "\n".join(json.dumps(l) for l in lines2)
    )
    parser = CodexParser()
    parser.parse(tmp_path)
    assert len(parser.conversations) == 2


# --- v3-specific tests ---

def test_codex_branches_one_per_conv(tmp_path):
    """v3: 1 Branch <conv>_main por Conversation."""
    path = _write_session(tmp_path)
    parser = CodexParser()
    parser.parse(path)
    assert len(parser.branches) == len(parser.conversations) == 1
    b = parser.branches[0]
    assert b.branch_id.endswith("_main")
    assert b.is_active is True
    assert b.source == "codex"


def test_codex_write_parquets(tmp_path):
    """v3: write_parquets gera 5 arquivos canonicos."""
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_session(raw)
    out_dir = tmp_path / "processed"
    parser = CodexParser()
    parser.parse(raw)
    stats = parser.write_parquets(out_dir)
    expected = {
        "codex_conversations.parquet",
        "codex_messages.parquet",
        "codex_tool_events.parquet",
        "codex_branches.parquet",
        "codex_agent_memories.parquet",
    }
    assert {p.name for p in out_dir.glob("*.parquet")} == expected
    assert stats["conversations"] == 1
    assert stats["branches"] == 1
    assert stats["agent_memories"] == 0


def test_codex_idempotent(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_session(raw)
    out_dir = tmp_path / "processed"
    p1 = CodexParser()
    p1.parse(raw)
    p1.write_parquets(out_dir)
    sizes_first = {p.name: p.stat().st_size for p in out_dir.glob("*.parquet")}
    p2 = CodexParser()
    p2.parse(raw)
    p2.write_parquets(out_dir)
    sizes_second = {p.name: p.stat().st_size for p in out_dir.glob("*.parquet")}
    assert sizes_first == sizes_second
