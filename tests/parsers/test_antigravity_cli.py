import json
import sqlite3
from pathlib import Path

from src.parsers.antigravity_cli import AntigravityCLIParser


CONVERSATION_ID = "conv-readable"


def _write_transcript(root: Path, conversation_id: str = CONVERSATION_ID) -> Path:
    logs = root / "brain" / conversation_id / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    records = [
        {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "status": "DONE", "created_at": "2026-08-30T14:00:00Z", "content": "Inspect this project."},
        {"step_index": 1, "type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE", "created_at": "2026-08-30T14:00:01Z", "content": "I will inspect it.", "thinking": "First inspect files.", "tool_calls": [{"name": "run_command", "args": {"command": "rg --files"}}]},
        {"step_index": 2, "type": "RUN_COMMAND", "source": "MODEL", "status": "DONE", "created_at": "2026-08-30T14:00:02Z", "content": "README.md\nsrc/main.py"},
    ]
    transcript = logs / "transcript.jsonl"
    transcript.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return transcript


def _setup_raw(tmp_path: Path) -> Path:
    raw = tmp_path / "Antigravity CLI"
    _write_transcript(raw)
    conversations = raw / "conversations"
    conversations.mkdir()
    db = conversations / f"{CONVERSATION_ID}.db"
    sqlite3.connect(db).close()
    (conversations / "conv-opaque.pb").write_bytes(b"encrypted legacy payload")
    (raw / "cache").mkdir()
    (raw / "cache" / "conversation_metadata.json").write_text(json.dumps({"conversations": {CONVERSATION_ID: {"summary": "Project inspection"}}}))
    (raw / "history.jsonl").write_text(json.dumps({"conversationId": CONVERSATION_ID, "display": "Inspect project", "workspace": "/tmp/project", "timestamp": 1}) + "\n")
    return raw


def _write_recovered_trajectory(root: Path, conversation_id: str = "conv-legacy") -> Path:
    recovered = root / "recovered"
    recovered.mkdir(parents=True, exist_ok=True)
    trajectory = {
        "cascadeId": conversation_id,
        "generatorMetadata": [{
            "plannerConfig": {"modelName": "legacy-model"},
            "chatModel": {"model": "legacy-chat-model"},
        }],
        "steps": [
            {
                "type": "CORTEX_STEP_TYPE_USER_INPUT",
                "status": "CORTEX_STEP_STATUS_DONE",
                "metadata": {"createdAt": "2026-08-29T12:00:00Z"},
                "userInput": {"userResponse": "Legacy question"},
            },
            {
                "type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE",
                "status": "CORTEX_STEP_STATUS_DONE",
                "metadata": {"createdAt": "2026-08-29T12:00:01Z"},
                "plannerResponse": {
                    "content": "Legacy answer",
                    "thinking": "Legacy reasoning",
                    "toolCalls": [{"name": "view_file", "args": {"path": "README.md"}}],
                },
            },
            {
                "type": "CORTEX_STEP_TYPE_ERROR_MESSAGE",
                "status": "CORTEX_STEP_STATUS_ERROR",
                "metadata": {"createdAt": "2026-08-29T12:00:02Z"},
                "errorMessage": {"error": {"userMessage": "Legacy operation failed"}},
            },
        ],
    }
    path = recovered / f"{conversation_id}.trajectory.json"
    path.write_text(json.dumps(trajectory))
    return path


def test_antigravity_parses_readable_trajectory_and_opaque_stub(tmp_path, monkeypatch):
    raw = _setup_raw(tmp_path)
    monkeypatch.setattr("src.extractors.cli.preservation.mark_cli_preservation", lambda parser: 0)
    parser = AntigravityCLIParser()
    parser.parse(raw)

    assert {c.conversation_id for c in parser.conversations} == {CONVERSATION_ID, "conv-opaque"}
    conversation = next(c for c in parser.conversations if c.conversation_id == CONVERSATION_ID)
    assert conversation.title == "Inspect project"
    assert conversation.project == "/tmp/project"
    assert conversation.summary == "Project inspection"
    assert conversation.message_count == 2
    assert [message.role for message in parser.messages] == ["user", "assistant"]
    assert parser.messages[1].thinking == "First inspect files."
    assert len(parser.events) == 2
    assert parser.events[0].tool_name == "run_command"
    assert parser.events[0].command == "rg --files"
    assert parser.events[1].event_type == "run_command"
    opaque = next(c for c in parser.conversations if c.conversation_id == "conv-opaque")
    assert opaque.message_count == 0
    assert len(parser.branches) == 2


def test_antigravity_writes_four_canonical_parquets(tmp_path, monkeypatch):
    raw = _setup_raw(tmp_path)
    monkeypatch.setattr("src.extractors.cli.preservation.mark_cli_preservation", lambda parser: 0)
    parser = AntigravityCLIParser()
    parser.parse(raw)
    output = tmp_path / "processed"
    stats = parser.write_parquets(output)
    assert stats == {"conversations": 2, "messages": 2, "tool_events": 2, "branches": 2}
    for table in ("conversations", "messages", "tool_events", "branches"):
        assert (output / f"antigravity_cli_{table}.parquet").exists()


def test_antigravity_parses_recovered_legacy_trajectory(tmp_path, monkeypatch):
    raw = tmp_path / "Antigravity CLI"
    conversations = raw / "conversations"
    conversations.mkdir(parents=True)
    (conversations / "conv-legacy.pb").write_bytes(b"opaque")
    recovered = _write_recovered_trajectory(raw)
    monkeypatch.setattr("src.extractors.cli.preservation.mark_cli_preservation", lambda parser: 0)

    parser = AntigravityCLIParser()
    parser.parse(raw)

    assert len(parser.conversations) == 1
    conversation = parser.conversations[0]
    assert conversation.conversation_id == "conv-legacy"
    assert conversation.message_count == 2
    assert conversation.model == "legacy-model"
    assert conversation.capture_method == "legacy_antigravity_daemon"
    assert [message.role for message in parser.messages] == ["user", "assistant"]
    assert parser.messages[0].content == "Legacy question"
    assert parser.messages[1].content == "Legacy answer"
    assert parser.messages[1].thinking == "Legacy reasoning"
    assert {event.event_type for event in parser.events} == {"tool_call", "error_message"}
    assert next(event for event in parser.events if event.event_type == "error_message").success is False
    assert parser._conv_source_files["conv-legacy"] == {
        "conversations/conv-legacy.pb",
        str(recovered.relative_to(raw)),
    }
    assert parser.branches[0].root_message_id == parser.messages[0].message_id
    assert parser.branches[0].leaf_message_id == parser.messages[-1].message_id


def test_current_transcript_takes_priority_over_recovered_trajectory(tmp_path, monkeypatch):
    raw = _setup_raw(tmp_path)
    _write_recovered_trajectory(raw, CONVERSATION_ID)
    monkeypatch.setattr("src.extractors.cli.preservation.mark_cli_preservation", lambda parser: 0)

    parser = AntigravityCLIParser()
    parser.parse(raw)

    conversation = next(c for c in parser.conversations if c.conversation_id == CONVERSATION_ID)
    assert conversation.capture_method == "extractor"
    assert conversation.message_count == 2
    assert all(message.content != "Legacy question" for message in parser.messages)
