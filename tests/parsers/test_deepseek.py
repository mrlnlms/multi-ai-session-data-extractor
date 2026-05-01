"""Testes do parser DeepSeek v3 (schema canonico).

Cobertura:
- Schema chat_session + chat_messages (formato API atual)
- thinking_content (R1) → Message.thinking
- search_results → ToolEvent + citations_json
- pinned, agent, model_type → settings_json + mode
- Branches via parent_id + current_message_id (int IDs)
- accumulated_token_usage → Message.token_count
- finish_reason via status + incomplete_message
- Files per msg → attachment_names
- Preservation
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.parsers.deepseek import DeepSeekParser


def _write_merged(tmp_path: Path, sessions: list[dict]) -> Path:
    merged = tmp_path / "DeepSeek"
    (merged / "conversations").mkdir(parents=True, exist_ok=True)
    for s in sessions:
        sid = s["chat_session"]["id"]
        (merged / "conversations" / f"{sid}.json").write_text(
            json.dumps(s, ensure_ascii=False), encoding="utf-8"
        )
    return merged


def _basic_session(sid="sess-1", title="Test", agent="chat", model_type="default", **session_overrides) -> dict:
    sess = {
        "id": sid,
        "title": title,
        "title_type": "SYSTEM",
        "model_type": model_type,
        "agent": agent,
        "version": 2,
        "is_empty": False,
        "pinned": False,
        "current_message_id": 2,
        "seq_id": 1,
        "inserted_at": 1774238947.92,
        "updated_at": 1774238984.83,
    }
    sess.update(session_overrides)
    msgs = [
        {
            "message_id": 1,
            "parent_id": None,
            "role": "USER",
            "content": "ola",
            "model": "",
            "inserted_at": 1774238950.0,
            "status": "FINISHED",
            "thinking_content": None,
            "thinking_elapsed_secs": None,
            "thinking_enabled": False,
            "search_enabled": False,
            "search_results": None,
            "search_status": None,
            "accumulated_token_usage": 0,
            "files": [],
            "feedback": None,
            "incomplete_message": None,
            "tips": [],
            "ban_edit": False,
            "ban_regenerate": False,
        },
        {
            "message_id": 2,
            "parent_id": 1,
            "role": "ASSISTANT",
            "content": "oi!",
            "model": "deepseek-chat",
            "inserted_at": 1774238955.5,
            "status": "FINISHED",
            "thinking_content": None,
            "thinking_elapsed_secs": None,
            "thinking_enabled": False,
            "search_enabled": False,
            "search_results": None,
            "search_status": None,
            "accumulated_token_usage": 100,
            "files": [],
            "feedback": None,
            "incomplete_message": None,
            "tips": [],
            "ban_edit": False,
            "ban_regenerate": False,
        },
    ]
    return {"chat_session": sess, "chat_messages": msgs}


def test_basic_parse(tmp_path):
    merged = _write_merged(tmp_path, [_basic_session()])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    assert len(p.conversations) == 1
    assert len(p.messages) == 2
    c = p.conversations[0]
    assert c.conversation_id == "sess-1"
    assert c.source == "deepseek"
    assert c.title == "Test"
    assert c.mode == "chat"
    assert c.url == "https://chat.deepseek.com/a/chat/s/sess-1"


def test_role_mapping_uppercase(tmp_path):
    """DeepSeek retorna USER/ASSISTANT (uppercase) — parser deve mapear."""
    merged = _write_merged(tmp_path, [_basic_session()])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    assert p.messages[0].role == "user"
    assert p.messages[1].role == "assistant"


def test_pinned_flag(tmp_path):
    merged = _write_merged(tmp_path, [_basic_session(pinned=True)])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    assert p.conversations[0].is_pinned is True


def test_agent_mode_to_research(tmp_path):
    merged = _write_merged(tmp_path, [_basic_session(agent="agent")])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    assert p.conversations[0].mode == "research"


def test_thinking_model_type_to_research(tmp_path):
    merged = _write_merged(tmp_path, [_basic_session(model_type="thinking")])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    assert p.conversations[0].mode == "research"


def test_r1_reasoning_to_thinking(tmp_path):
    sess = _basic_session()
    sess["chat_messages"][1]["thinking_content"] = "Hmm, let me reason..."
    sess["chat_messages"][1]["thinking_elapsed_secs"] = 5.89
    sess["chat_messages"][1]["thinking_enabled"] = True
    merged = _write_merged(tmp_path, [sess])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    msg_asst = next(m for m in p.messages if m.role == "assistant")
    assert msg_asst.thinking == "Hmm, let me reason..."


def test_token_count_from_accumulated(tmp_path):
    merged = _write_merged(tmp_path, [_basic_session()])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    msg_asst = next(m for m in p.messages if m.role == "assistant")
    assert msg_asst.token_count == 100


def test_finish_reason_from_status(tmp_path):
    merged = _write_merged(tmp_path, [_basic_session()])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    assert all(m.finish_reason == "stop" for m in p.messages)


def test_finish_reason_incomplete(tmp_path):
    sess = _basic_session()
    sess["chat_messages"][1]["incomplete_message"] = "User stopped"
    merged = _write_merged(tmp_path, [sess])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    msg_asst = next(m for m in p.messages if m.role == "assistant")
    assert msg_asst.finish_reason == "incomplete"


def test_search_results_to_event_and_citations(tmp_path):
    sess = _basic_session()
    sess["chat_messages"][1]["search_enabled"] = True
    sess["chat_messages"][1]["search_results"] = [
        {"title": "Result A", "url": "https://a.com"},
        {"title": "Result B", "url": "https://b.com"},
    ]
    sess["chat_messages"][1]["search_status"] = "DONE"
    merged = _write_merged(tmp_path, [sess])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    # ToolEvents
    assert len(p.events) == 2
    call = next(e for e in p.events if e.event_type == "search_call")
    result = next(e for e in p.events if e.event_type == "search_result")
    assert call.tool_name == "web_search"
    assert json.loads(result.result)[0]["title"] == "Result A"
    # Citations inline em msg
    msg_asst = next(m for m in p.messages if m.role == "assistant")
    cits = json.loads(msg_asst.citations_json)
    assert len(cits) == 2


def test_branches_via_parent_id(tmp_path):
    """Branch fork: msg-1 tem 2 children (msg-2 main, msg-3 alternativa)."""
    sess = _basic_session(sid="sess-fork")
    sess["chat_session"]["current_message_id"] = 2
    sess["chat_messages"].append({
        "message_id": 3,
        "parent_id": 1,
        "role": "ASSISTANT",
        "content": "alternative answer",
        "model": "deepseek-chat",
        "inserted_at": 1774238960.0,
        "status": "FINISHED",
        "thinking_content": None,
        "thinking_enabled": False,
        "search_enabled": False,
        "search_results": None,
        "search_status": None,
        "accumulated_token_usage": 80,
        "files": [],
        "feedback": None,
        "incomplete_message": None,
        "tips": [],
        "ban_edit": False,
        "ban_regenerate": False,
    })
    merged = _write_merged(tmp_path, [sess])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    branches = {b.branch_id: b for b in p.branches}
    assert "sess-fork_main" in branches
    assert any(bid.startswith("sess-fork_branch_") for bid in branches)
    msg3 = next(m for m in p.messages if m.message_id == "3")
    assert msg3.branch_id != "sess-fork_main"


def test_files_to_attachment_names(tmp_path):
    sess = _basic_session()
    sess["chat_messages"][0]["files"] = [
        {"name": "data.csv"},
        {"name": "image.png"},
    ]
    merged = _write_merged(tmp_path, [sess])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    msg_user = next(m for m in p.messages if m.role == "user")
    names = json.loads(msg_user.attachment_names)
    assert "data.csv" in names


def test_settings_json_includes_thinking_total(tmp_path):
    sess = _basic_session()
    sess["chat_messages"][1]["thinking_enabled"] = True
    sess["chat_messages"][1]["thinking_elapsed_secs"] = 3.5
    merged = _write_merged(tmp_path, [sess])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    settings = json.loads(p.conversations[0].settings_json)
    assert settings["thinking_elapsed_total_secs"] == 3.5
    assert settings["agent"] == "chat"


def test_save_writes_parquets(tmp_path):
    merged = _write_merged(tmp_path, [_basic_session()])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    out = tmp_path / "processed"
    p.save(out)
    assert (out / "deepseek_conversations.parquet").exists()
    assert (out / "deepseek_messages.parquet").exists()
    assert (out / "deepseek_branches.parquet").exists()


def test_preservation_via_explicit_flag(tmp_path):
    sess = _basic_session()
    sess["_preserved_missing"] = True
    sess["_last_seen_in_server"] = "2026-04-01"
    merged = _write_merged(tmp_path, [sess])
    p = DeepSeekParser(merged_root=merged)
    p.parse(merged)
    assert p.conversations[0].is_preserved_missing is True
