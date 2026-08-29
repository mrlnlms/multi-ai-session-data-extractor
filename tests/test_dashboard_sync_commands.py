"""Pipeline command routing: web syncs must parse before unify."""

from __future__ import annotations

from dashboard import sync


def test_parse_command_exists_for_every_web_platform():
    for platform in sync.WEB_PLATFORMS:
        command = sync.parse_command(platform)
        assert command is not None
        assert command[-1].endswith("-parse.py")


def test_parse_command_is_none_for_cli_platforms():
    for platform in ("Claude Code", "Codex", "Gemini CLI"):
        assert sync.parse_command(platform) is None


def test_streaming_web_sync_runs_parser_after_success(monkeypatch):
    calls = []

    def fake_stream(command, on_line, tail_size, timeout):
        calls.append(command)
        return 0, command[-1]

    monkeypatch.setattr(sync, "_stream", fake_stream)
    rc, _tail = sync.run_sync_streaming("Claude.ai", lambda _line: None)

    assert rc == 0
    assert calls[0][-1].endswith("claude-sync.py")
    assert calls[1][-1].endswith("claude-parse.py")


def test_streaming_failed_sync_does_not_parse(monkeypatch):
    calls = []

    def fake_stream(command, on_line, tail_size, timeout):
        calls.append(command)
        return 1, "failed"

    monkeypatch.setattr(sync, "_stream", fake_stream)
    rc, _tail = sync.run_sync_streaming("Claude.ai", lambda _line: None)

    assert rc == 1
    assert len(calls) == 1


def test_streaming_cli_sync_does_not_double_parse(monkeypatch):
    calls = []

    def fake_stream(command, on_line, tail_size, timeout):
        calls.append(command)
        return 0, "ok"

    monkeypatch.setattr(sync, "_stream", fake_stream)
    rc, _tail = sync.run_sync_streaming("Codex", lambda _line: None)

    assert rc == 0
    assert len(calls) == 1
