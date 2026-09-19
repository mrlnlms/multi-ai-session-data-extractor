from __future__ import annotations

import base64
import inspect
import json
import sys

from src.assets.models import AssetScope
from src.assets.vault import AssetVault
from src.platforms.antigravity_cli.parser import AntigravityCLIParser
from src.platforms.claude_code.parser import ClaudeCodeParser
from src.platforms.codex.parser import CodexParser
from src.platforms.gemini_cli.parser import GeminiCLIParser


def _vault(data_root, tmp_path) -> AssetVault:
    return AssetVault(data_root / "assets", runtime_root=tmp_path / "runtime")


def test_claude_code_parser_commits_inline_image_and_exact_position(tmp_path):
    data_root = tmp_path / "data"
    raw = data_root / "raw" / "Claude Code"
    project = raw / "project"
    project.mkdir(parents=True)
    payload = b"claude image"
    event = {
        "type": "user",
        "uuid": "message-1",
        "timestamp": "2026-09-16T12:00:00Z",
        "sessionId": "session-1",
        "cwd": "/project",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [
                {"type": "text", "text": "inspect"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(payload).decode(),
                    },
                },
            ],
        },
    }
    (project / "session-1.jsonl").write_text(json.dumps(event) + "\n")
    vault = _vault(data_root, tmp_path)

    parser = ClaudeCodeParser(asset_vault=vault, asset_data_root=data_root)
    parser.parse(raw)

    state = vault.load_state(AssetScope("claude_code"))
    assert len(state.by_type["delivery"]) == len(state.by_type["appearance"]) == 1
    appearance = state.by_type["appearance"][0].payload
    assert appearance["message_id"] == "message-1"
    assert appearance["ordinal"] == 0
    assert appearance["content_block_index"] == 1
    assert (data_root / parser.assets[0].asset_path).read_bytes() == payload


def test_codex_parser_commits_data_uri_at_exact_block(tmp_path):
    data_root = tmp_path / "data"
    raw = data_root / "raw" / "Codex"
    sessions = raw / "2026" / "09" / "16"
    sessions.mkdir(parents=True)
    payload = b"codex image"
    records = [
        {
            "timestamp": "2026-09-16T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": "session-1", "cwd": "/project"},
        },
        {
            "timestamp": "2026-09-16T12:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "inspect"},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,"
                        + base64.b64encode(payload).decode(),
                    },
                ],
            },
        },
    ]
    (sessions / "rollout-fixture.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n"
    )
    vault = _vault(data_root, tmp_path)

    parser = CodexParser(asset_vault=vault, asset_data_root=data_root)
    parser.parse(raw)

    appearance = vault.load_state(AssetScope("codex")).by_type["appearance"][0].payload
    assert appearance["message_id"] == "session-1_1"
    assert appearance["ordinal"] == 0
    assert appearance["content_block_index"] == 1
    assert (data_root / parser.assets[0].asset_path).read_bytes() == payload


def test_antigravity_parser_commits_delivered_artifact(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    raw = data_root / "raw" / "Antigravity CLI"
    logs = raw / "brain" / "conversation-1" / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    content = "# generated\n"
    records = [
        {
            "step_index": 0,
            "type": "PLANNER_RESPONSE",
            "source": "MODEL",
            "status": "DONE",
            "created_at": "2026-09-16T12:00:00Z",
            "content": "done",
            "tool_calls": [
                {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": "report.md",
                        "CodeContent": content,
                        "ArtifactMetadata": {"UserFacing": True},
                    },
                }
            ],
        }
    ]
    (logs / "transcript.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n"
    )
    monkeypatch.setattr(
        "src.capture.cli.preservation.mark_cli_preservation", lambda parser: 0
    )
    vault = _vault(data_root, tmp_path)

    parser = AntigravityCLIParser(asset_vault=vault, asset_data_root=data_root)
    parser.parse(raw)

    appearance = vault.load_state(AssetScope("antigravity_cli")).by_type[
        "appearance"
    ][0].payload
    assert appearance["message_id"] == "conversation-1_step_0"
    assert appearance["role"] == "output"
    assert appearance["ordinal"] == 0
    assert (data_root / parser.assets[0].asset_path).read_text() == content


def test_gemini_cli_parser_commits_empty_capture(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    raw = data_root / "raw" / "Gemini CLI"
    chats = raw / "project" / "chats"
    chats.mkdir(parents=True)
    session = {
        "sessionId": "session-1",
        "startTime": "2026-09-16T12:00:00Z",
        "lastUpdated": "2026-09-16T12:00:00Z",
        "messages": [],
    }
    (chats / "session-fixture.json").write_text(json.dumps(session))
    monkeypatch.setattr(
        "src.capture.cli.preservation.mark_cli_preservation", lambda parser: 0
    )
    vault = _vault(data_root, tmp_path)

    GeminiCLIParser(asset_vault=vault, asset_data_root=data_root).parse(raw)

    state = vault.load_state(AssetScope("gemini_cli"))
    assert len(state.committed_captures) == 1
    assert state.by_type["delivery"] == ()


def test_all_cli_sync_commands_expose_explicit_opt_in():
    from src.platforms.antigravity_cli.commands import sync as antigravity_sync
    from src.platforms.claude_code.commands import sync as claude_sync
    from src.platforms.codex.commands import sync as codex_sync
    from src.platforms.gemini_cli.commands import sync as gemini_sync

    for module in (claude_sync, codex_sync, gemini_sync, antigravity_sync):
        signature = inspect.signature(module.main)
        assert signature.parameters["asset_vault"].default is None
        assert signature.parameters["asset_data_root"].default is None


def test_all_cli_sync_commands_forward_explicit_vault_to_parser(tmp_path, monkeypatch):
    from src.platforms.antigravity_cli.commands import sync as antigravity_sync
    from src.platforms.claude_code.commands import sync as claude_sync
    from src.platforms.codex.commands import sync as codex_sync
    from src.platforms.gemini_cli.commands import sync as gemini_sync

    modules = (
        (claude_sync, "ClaudeCodeParser"),
        (codex_sync, "CodexParser"),
        (gemini_sync, "GeminiCLIParser"),
        (antigravity_sync, "AntigravityCLIParser"),
    )
    for index, (module, parser_name) in enumerate(modules):
        root = tmp_path / str(index)
        raw = root / "data" / "raw" / parser_name
        processed = root / "data" / "processed" / parser_name
        raw.mkdir(parents=True)
        received = {}

        class FakeParser:
            files_seen = 0
            files_parsed = 0
            files_skipped = 0

            def __init__(self, **kwargs):
                received.update(kwargs)

            def parse(self, *args, **kwargs):
                return None

            def write_parquets(self, output_dir):
                return {
                    "conversations": 0,
                    "messages": 0,
                    "tool_events": 0,
                    "branches": 0,
                    "agent_memories": 0,
                    "assets": 0,
                    "asset_links": 0,
                }

        vault = _vault(root / "data", root)
        monkeypatch.setattr(module, "RAW_DIR", raw)
        monkeypatch.setattr(module, "PROCESSED_DIR", processed)
        monkeypatch.setattr(module, parser_name, FakeParser)
        monkeypatch.setattr(
            module, "_copy_source", lambda source: {"new": [], "updated": []}
        )
        if hasattr(module, "current_source_files"):
            monkeypatch.setattr(module, "current_source_files", lambda source: set())
        monkeypatch.setattr(sys, "argv", ["sync"])

        assert module.main(asset_vault=vault, asset_data_root=root / "data") == 0
        assert received == {
            "asset_vault": vault,
            "asset_data_root": root / "data",
        }
