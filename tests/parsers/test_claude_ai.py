"""Testes do parser Claude.ai v3 (schema canonico).

Cobertura:
- Layout merged (data/merged/Claude.ai/{conversations,projects}/<uuid>.json)
- Schema fields: is_pinned (do is_starred), is_temporary, summary preservado em raw
- Branches via parent_message_uuid + current_leaf_message_uuid
- Thinking blocks → Message.thinking
- tool_use / tool_result → ToolEvent (incl. MCP via integration_name)
- Attachments → Message.attachment_names
- Files → Message.asset_paths via assets_root
- Preservation flags
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.parsers.claude_ai import ClaudeAIParser


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _write_merged(tmp_path: Path, convs: list[dict], projects: list[dict] | None = None) -> Path:
    """Cria layout merged em tmp_path: conversations/<uuid>.json, projects/<uuid>.json."""
    merged = tmp_path / "Claude.ai"
    (merged / "conversations").mkdir(parents=True, exist_ok=True)
    (merged / "projects").mkdir(parents=True, exist_ok=True)
    (merged / "assets").mkdir(parents=True, exist_ok=True)
    for c in convs:
        (merged / "conversations" / f"{c['uuid']}.json").write_text(
            json.dumps(c, ensure_ascii=False), encoding="utf-8"
        )
    for p in projects or []:
        (merged / "projects" / f"{p['uuid']}.json").write_text(
            json.dumps(p, ensure_ascii=False), encoding="utf-8"
        )
    return merged


def _basic_conv(uuid="conv-1", name="Test", **overrides) -> dict:
    """Helper: conv minimamente valida com 1 user + 1 assistant."""
    base = {
        "uuid": uuid,
        "name": name,
        "summary": "",
        "model": "claude-sonnet-4-5-20250929",
        "platform": "CLAUDE_AI",
        "created_at": "2025-06-20T09:00:00.000000Z",
        "updated_at": "2025-06-20T09:45:00.000000Z",
        "is_starred": False,
        "is_temporary": False,
        "current_leaf_message_uuid": "msg-2",
        "settings": {},
        "chat_messages": [
            {
                "uuid": "msg-1",
                "parent_message_uuid": "00000000-0000-4000-8000-000000000000",
                "sender": "human",
                "index": "0",
                "text": "",
                "content": [{"type": "text", "text": "hello"}],
                "created_at": "2025-06-20T09:00:00.000000Z",
                "updated_at": "2025-06-20T09:00:00.000000Z",
                "attachments": [],
                "files": [],
                "sync_sources": [],
            },
            {
                "uuid": "msg-2",
                "parent_message_uuid": "msg-1",
                "sender": "assistant",
                "index": "1",
                "stop_reason": "stop_sequence",
                "text": "",
                "content": [{"type": "text", "text": "hi there"}],
                "created_at": "2025-06-20T09:00:30.000000Z",
                "updated_at": "2025-06-20T09:00:30.000000Z",
                "attachments": [],
                "files": [],
                "sync_sources": [],
            },
        ],
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------
# Basic parsing
# ----------------------------------------------------------------------

def test_basic_parse(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv()])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)

    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2
    conv = parser.conversations[0]
    assert conv.conversation_id == "conv-1"
    assert conv.source == "claude_ai"
    assert conv.title == "Test"
    assert conv.mode == "chat"
    assert conv.message_count == 2
    assert conv.url == "https://claude.ai/chat/conv-1"


def test_role_mapping(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv()])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert parser.messages[0].role == "user"
    assert parser.messages[1].role == "assistant"


def test_empty_title_becomes_none(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv(name="")])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert parser.conversations[0].title is None


def test_text_blocks_concatenated(tmp_path):
    conv = _basic_conv()
    conv["chat_messages"][1]["content"] = [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert parser.messages[1].content == "first\n\nsecond"


# ----------------------------------------------------------------------
# Cross-platform: is_starred → is_pinned + is_temporary
# ----------------------------------------------------------------------

def test_is_starred_maps_to_is_pinned(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv(is_starred=True)])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert parser.conversations[0].is_pinned is True


def test_is_temporary_preserved(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv(is_temporary=True)])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert parser.conversations[0].is_temporary is True


def test_defaults_when_flags_absent(tmp_path):
    conv = _basic_conv()
    conv.pop("is_starred", None)
    conv.pop("is_temporary", None)
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert parser.conversations[0].is_pinned is False
    assert parser.conversations[0].is_temporary is False


# ----------------------------------------------------------------------
# Thinking blocks
# ----------------------------------------------------------------------

def test_thinking_block_to_message_thinking(tmp_path):
    conv = _basic_conv()
    conv["chat_messages"][1]["content"] = [
        {"type": "thinking", "thinking": "Let me reason..."},
        {"type": "text", "text": "answer"},
    ]
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    msg = parser.messages[1]
    assert msg.thinking == "Let me reason..."
    assert msg.content == "answer"
    assert "thinking" in msg.content_types
    assert "text" in msg.content_types


def test_no_thinking_means_none(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv()])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert parser.messages[1].thinking is None


# ----------------------------------------------------------------------
# Tool use / tool result → ToolEvent
# ----------------------------------------------------------------------

def test_tool_use_creates_event(tmp_path):
    conv = _basic_conv()
    conv["chat_messages"][1]["content"] = [
        {
            "type": "tool_use",
            "id": "toolu_abc",
            "name": "web_search",
            "input": {"query": "claude api"},
            "message": "Searching the web",
        },
        {"type": "text", "text": "results follow"},
    ]
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert len(parser.events) == 1
    evt = parser.events[0]
    assert evt.event_type == "search_call"
    assert evt.tool_name == "web_search"
    assert evt.event_id == "toolu_abc"


def test_tool_result_creates_event(tmp_path):
    conv = _basic_conv()
    conv["chat_messages"][1]["content"] = [
        {
            "type": "tool_use",
            "id": "toolu_abc",
            "name": "web_search",
            "input": {"query": "x"},
        },
        {
            "type": "tool_result",
            "tool_use_id": "toolu_abc",
            "name": "web_search",
            "content": [{"type": "knowledge", "title": "X", "url": "https://x"}],
            "is_error": False,
        },
    ]
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert len(parser.events) == 2
    call, result = parser.events
    assert call.event_type == "search_call"
    assert result.event_type == "search_result"
    assert result.event_id == "toolu_abc_result"
    assert result.success is True


def test_mcp_detected_via_integration_name(tmp_path):
    conv = _basic_conv()
    conv["chat_messages"][1]["content"] = [
        {
            "type": "tool_use",
            "id": "toolu_mcp",
            "name": "google_drive_search",
            "input": {"q": "hello"},
            "integration_name": "Google Drive",
            "integration_icon_url": "https://example.com/g.png",
        },
    ]
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    evt = parser.events[0]
    assert evt.event_type == "mcp_search_call"
    metadata = json.loads(evt.metadata_json)
    assert metadata["is_mcp"] is True
    assert metadata["integration_name"] == "Google Drive"


# ----------------------------------------------------------------------
# Branches via parent_message_uuid
# ----------------------------------------------------------------------

def test_main_branch_via_current_leaf(tmp_path):
    conv = _basic_conv()
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert len(parser.branches) == 1
    br = parser.branches[0]
    assert br.is_active is True
    assert br.branch_id == "conv-1_main"
    assert br.root_message_id == "msg-1"
    assert br.leaf_message_id == "msg-2"
    # Todas as msgs marcadas com main branch
    assert all(m.branch_id == "conv-1_main" for m in parser.messages)


def test_branches_with_fork(tmp_path):
    """Conv com fork: msg-2 tem 2 children (msg-3 main, msg-4 secundaria)."""
    conv = {
        "uuid": "conv-fork",
        "name": "fork test",
        "summary": "",
        "model": "claude-sonnet-4-5",
        "platform": "CLAUDE_AI",
        "created_at": "2025-06-20T09:00:00.000000Z",
        "updated_at": "2025-06-20T09:45:00.000000Z",
        "is_starred": False,
        "is_temporary": False,
        "current_leaf_message_uuid": "msg-3",
        "settings": {},
        "chat_messages": [
            {"uuid": "msg-1", "parent_message_uuid": "00000000-0000-4000-8000-000000000000",
             "sender": "human", "index": "0", "content": [{"type": "text", "text": "q"}],
             "created_at": "2025-06-20T09:00:00Z", "updated_at": "2025-06-20T09:00:00Z",
             "attachments": [], "files": [], "sync_sources": []},
            {"uuid": "msg-2", "parent_message_uuid": "msg-1",
             "sender": "assistant", "index": "1", "content": [{"type": "text", "text": "a1"}],
             "created_at": "2025-06-20T09:00:30Z", "updated_at": "2025-06-20T09:00:30Z",
             "attachments": [], "files": [], "sync_sources": []},
            {"uuid": "msg-3", "parent_message_uuid": "msg-2",  # main
             "sender": "human", "index": "2", "content": [{"type": "text", "text": "q2"}],
             "created_at": "2025-06-20T09:01:00Z", "updated_at": "2025-06-20T09:01:00Z",
             "attachments": [], "files": [], "sync_sources": []},
            {"uuid": "msg-4", "parent_message_uuid": "msg-2",  # branch off main
             "sender": "human", "index": "2", "content": [{"type": "text", "text": "q2-alt"}],
             "created_at": "2025-06-20T09:01:30Z", "updated_at": "2025-06-20T09:01:30Z",
             "attachments": [], "files": [], "sync_sources": []},
        ],
    }
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    branches = {b.branch_id: b for b in parser.branches}
    assert "conv-fork_main" in branches
    assert any(bid.startswith("conv-fork_branch_") for bid in branches)
    assert branches["conv-fork_main"].is_active is True
    # msg-4 deve estar numa branch secundaria
    msg4 = next(m for m in parser.messages if m.message_id == "msg-4")
    assert msg4.branch_id != "conv-fork_main"


# ----------------------------------------------------------------------
# Attachments + files
# ----------------------------------------------------------------------

def test_attachments_to_attachment_names(tmp_path):
    conv = _basic_conv()
    conv["chat_messages"][0]["attachments"] = [
        {"id": "a1", "file_name": "doc.pdf", "extracted_content": "...content..."},
    ]
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    msg = parser.messages[0]
    assert msg.attachment_names is not None
    names = json.loads(msg.attachment_names)
    assert "doc.pdf" in names
    assert "attachment" in msg.content_types


def test_files_resolve_to_asset_paths(tmp_path):
    conv = _basic_conv()
    conv["chat_messages"][0]["files"] = [
        {"file_uuid": "abc-123", "file_name": "img.png", "file_kind": "image"},
    ]
    merged = _write_merged(tmp_path, [conv])
    # Simula asset baixado
    (merged / "assets" / "abc-123_preview.webp").write_bytes(b"fake-webp")

    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    msg = parser.messages[0]
    assert msg.asset_paths is not None
    assert any("abc-123_preview.webp" in p for p in msg.asset_paths)
    assert "file" in msg.content_types


# ----------------------------------------------------------------------
# Preservation flags
# ----------------------------------------------------------------------

def test_preservation_via_explicit_flag(tmp_path):
    conv = _basic_conv()
    conv["_preserved_missing"] = True
    conv["_last_seen_in_server"] = "2026-04-01"
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    assert parser.conversations[0].is_preserved_missing is True


def test_preservation_via_lag(tmp_path):
    """Conv com last_seen mais antiga que outras → flagged como preserved."""
    old_conv = _basic_conv(uuid="conv-old")
    old_conv["_last_seen_in_server"] = "2026-03-01"
    new_conv = _basic_conv(uuid="conv-new")
    new_conv["_last_seen_in_server"] = "2026-05-01"
    merged = _write_merged(tmp_path, [old_conv, new_conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    by_id = {c.conversation_id: c for c in parser.conversations}
    assert by_id["conv-old"].is_preserved_missing is True
    assert by_id["conv-new"].is_preserved_missing is False


# ----------------------------------------------------------------------
# Project metadata
# ----------------------------------------------------------------------

def test_conversation_links_to_project(tmp_path):
    conv = _basic_conv()
    conv["project_uuid"] = "proj-1"
    conv["project"] = {"uuid": "proj-1", "name": "Q4 Research"}
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    c = parser.conversations[0]
    assert c.project_id == "proj-1"
    assert c.project == "Q4 Research"


def test_project_metadata_df(tmp_path):
    conv = _basic_conv()
    project = {
        "uuid": "proj-1",
        "name": "Q4",
        "description": "research",
        "prompt_template": "you are...",
        "is_private": True,
        "is_starred": False,
        "is_starter_project": False,
        "created_at": "2025-08-01T10:00:00Z",
        "updated_at": "2025-09-15T14:00:00Z",
        "docs": [{"uuid": "d1", "file_name": "g.md", "content": "x"}],
        "files": [],
        "docs_count": "1",
        "files_count": "0",
    }
    merged = _write_merged(tmp_path, [conv], projects=[project])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    df = parser.project_metadata_df()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["project_id"] == "proj-1"
    assert row["docs_count"] == 1
    assert row["files_count"] == 0


# ----------------------------------------------------------------------
# Save end-to-end
# ----------------------------------------------------------------------

def test_save_writes_parquets(tmp_path):
    conv = _basic_conv()
    conv["chat_messages"][1]["content"] = [
        {"type": "thinking", "thinking": "..."},
        {"type": "tool_use", "id": "tu1", "name": "web_search", "input": {}},
        {"type": "text", "text": "ok"},
    ]
    merged = _write_merged(tmp_path, [conv])
    parser = ClaudeAIParser(merged_root=merged)
    parser.parse(merged)
    out = tmp_path / "processed"
    parser.save(out)
    assert (out / "claude_ai_conversations.parquet").exists()
    assert (out / "claude_ai_messages.parquet").exists()
    assert (out / "claude_ai_tool_events.parquet").exists()
    assert (out / "claude_ai_branches.parquet").exists()
