"""Pipeline command routing: web syncs must parse before unify."""

from __future__ import annotations

from src.workflows import execution as sync
from src.accounts import RunnableAccount


PROJECT_ROOT = sync.PROJECT_ROOT


def test_parse_command_exists_for_every_web_platform():
    for platform in sync.WEB_PLATFORMS:
        command = sync.parse_command(platform)
        assert command is not None
        if platform in sync.PLATFORM_COMMAND_PACKAGES:
            assert command[1:] == [
                "-m",
                f"{sync.PLATFORM_COMMAND_PACKAGES[platform]}.parse",
            ]
        else:
            assert command[-1].endswith("/parse.py")


def test_parse_command_is_none_for_cli_platforms():
    for platform in ("Claude Code", "Codex", "Gemini CLI", "Antigravity CLI"):
        assert sync.parse_command(platform) is None


def test_streaming_web_sync_runs_parser_after_success(monkeypatch):
    calls = []

    def fake_stream(command, on_line, tail_size, timeout, **kwargs):
        calls.append(command)
        return 0, command[-1]

    monkeypatch.setattr(sync, "_stream", fake_stream)
    monkeypatch.setattr(sync, "runnable_accounts", lambda _platform: (RunnableAccount("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "default"),))
    rc, _tail = sync.run_sync_streaming("Claude.ai", lambda _line: None)

    assert rc == 0
    assert calls[0][1:] == ["-m", "src.platforms.claude_ai.commands.sync", "--profile", "default"]
    assert calls[1][1:] == ["-m", "src.platforms.claude_ai.commands.parse"]


def test_migrated_sync_command_uses_platform_module():
    assert sync.sync_command("ChatGPT", "account-2") == [
        sync.sys.executable,
        "-m",
        "src.platforms.chatgpt.commands.sync",
        "--no-voice-pass",
        "--account",
        "account-2",
    ]


def test_migrated_cli_sync_command_uses_platform_module():
    assert sync.sync_command("Codex")[1:] == [
        "-m",
        "src.platforms.codex.commands.sync",
    ]


def test_streaming_failed_sync_does_not_parse(monkeypatch):
    calls = []

    def fake_stream(command, on_line, tail_size, timeout, **kwargs):
        calls.append(command)
        return 1, "failed"

    monkeypatch.setattr(sync, "_stream", fake_stream)
    monkeypatch.setattr(sync, "runnable_accounts", lambda _platform: (
        RunnableAccount("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "default"),
        RunnableAccount("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "account-2"),
    ))
    rc, _tail = sync.run_sync_streaming("Claude.ai", lambda _line: None)

    assert rc == 1
    assert len(calls) == 1


def test_streaming_cli_sync_does_not_double_parse(monkeypatch):
    calls = []

    def fake_stream(command, on_line, tail_size, timeout, **kwargs):
        calls.append(command)
        return 0, "ok"

    monkeypatch.setattr(sync, "_stream", fake_stream)
    rc, _tail = sync.run_sync_streaming("Codex", lambda _line: None)

    assert rc == 0
    assert len(calls) == 1


def test_streaming_vault_mode_propagates_validated_environment(monkeypatch, tmp_path):
    calls = []

    def fake_stream(command, on_line, tail_size, timeout, extra_env=None):
        calls.append((command, extra_env))
        return 0, "ok"

    monkeypatch.setattr(sync, "_stream", fake_stream)
    monkeypatch.setattr(sync, "runnable_accounts", lambda _platform: (RunnableAccount("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "default"),))
    data_root = tmp_path / "data"
    rc, _tail = sync.run_sync_streaming(
        "Claude.ai",
        lambda _line: None,
        asset_mode="vault",
        vault_root=data_root / "assets",
        data_root=data_root,
    )

    assert rc == 0
    assert len(calls) == 2
    expected = {
            "AI_ARCHIVE_ASSET_MODE": "vault",
            "AI_ARCHIVE_ASSET_VAULT_ROOT": str(data_root / "assets"),
            "AI_ARCHIVE_ASSET_DATA_ROOT": str(data_root),
    }
    assert calls[0][1] == {**expected, "AI_ARCHIVE_ACCOUNT_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
    assert calls[1][1] == expected


def test_streaming_web_sync_runs_each_account_then_parses_once(monkeypatch):
    calls = []
    lines = []

    def fake_stream(command, on_line, tail_size, timeout, **kwargs):
        calls.append(command)
        return 0, "ok"

    monkeypatch.setattr(sync, "_stream", fake_stream)
    monkeypatch.setattr(sync, "runnable_accounts", lambda _platform: (
        RunnableAccount("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "default"),
        RunnableAccount("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "account-2"),
    ))

    rc, _tail = sync.run_sync_streaming("ChatGPT", lines.append)

    assert rc == 0
    assert calls[0][-2:] == ["--account", "default"]
    assert calls[1][-2:] == ["--account", "account-2"]
    assert calls[2][1:] == ["-m", "src.platforms.chatgpt.commands.parse"]
    assert sum("=== Parse ChatGPT" in line for line in lines) == 1


def test_streaming_web_failure_on_later_account_blocks_parser(monkeypatch):
    calls = []

    def fake_stream(command, on_line, tail_size, timeout, **kwargs):
        calls.append(command)
        return (9, "failed") if "account-2" in command else (0, "ok")

    monkeypatch.setattr(sync, "_stream", fake_stream)
    monkeypatch.setattr(sync, "runnable_accounts", lambda _platform: (
        RunnableAccount("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "default"),
        RunnableAccount("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "account-2"),
    ))

    rc, tail = sync.run_sync_streaming("ChatGPT", lambda _line: None)

    assert rc == 9
    assert tail == "failed"
    assert len(calls) == 2
