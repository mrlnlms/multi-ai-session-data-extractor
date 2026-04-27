import pytest
import pandas as pd
from pathlib import Path
from src.parsers.terminal_claude_code import TerminalClaudeCodeParser


FIXTURE_SIMPLE = """╭─── Claude Code v2.1.38 ──────────────────────────────────────────────────────╮
│                                        │ Tips for getting started            │
│          Welcome back Marlon!          │ Run /init to create a CLAUDE.md fi… │
│                 ▐▛███▜▌                │                                     │
│                ▝▜█████▛▘               │                                     │
│                  ▘▘ ▝▝                 │                                     │
│         Opus 4.6 · Claude Max          │                                     │
│   ~/Desktop/local-workbench/obsidian   │                                     │
╰──────────────────────────────────────────────────────────────────────────────╯

❯ olá, qual vault tem o plugin codemaker?

⏺ Vou procurar o plugin "codemaker" nas pastas de plugins de cada vault.

⏺ Bash(mdfind -name "codemaker" -onlyin /Users/mosx)
  ⎿  /Users/mosx/Library/CloudStorage/path/to/CodeMaker

⏺ Encontrei! O plugin está no vault local-workbench.
"""

FIXTURE_MULTI_TURN = """╭─── Claude Code v2.1.37 ──────────────────────────────────────────────────────╮
│         Opus 4.6 · Claude Max          │                                     │
│         ~/Desktop                      │                                     │
╰──────────────────────────────────────────────────────────────────────────────╯

❯ primeira pergunta do usuario

⏺ Primeira resposta do assistant.

❯ segunda pergunta do usuario

⏺ Segunda resposta do assistant.

⏺ Read(src/main.py)
  ⎿  conteudo do arquivo
"""

FIXTURE_NO_TOOLS = """╭─── Claude Code v2.1.38 ──────────────────────────────────────────────────────╮
│         Opus 4.6 · Claude Max          │                                     │
│         ~/Desktop                      │                                     │
╰──────────────────────────────────────────────────────────────────────────────╯

❯ explica o que é TDD

⏺ TDD (Test-Driven Development) é uma prática onde você escreve
  os testes antes do código de produção.
"""


def _write_fixture(tmp_path, filename, content):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return tmp_path


def test_terminal_basic(tmp_path):
    _write_fixture(tmp_path, "20260210 - test session.txt", FIXTURE_SIMPLE)
    parser = TerminalClaudeCodeParser()
    parser.parse(tmp_path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2
    conv = parser.conversations[0]
    assert conv.source == "claude_code"
    assert conv.mode == "cli"
    assert conv.message_count == 2


def test_terminal_roles(tmp_path):
    _write_fixture(tmp_path, "20260210 - test.txt", FIXTURE_SIMPLE)
    parser = TerminalClaudeCodeParser()
    parser.parse(tmp_path)
    roles = [m.role for m in parser.messages]
    assert roles == ["user", "assistant"]


def test_terminal_tool_events(tmp_path):
    _write_fixture(tmp_path, "20260210 - test.txt", FIXTURE_SIMPLE)
    parser = TerminalClaudeCodeParser()
    parser.parse(tmp_path)
    assert len(parser.events) == 1
    evt = parser.events[0]
    assert evt.tool_name == "Bash"
    assert evt.event_type == "tool_call"
    assert "mdfind" in evt.command
    assert evt.source == "claude_code"


def test_terminal_multi_turn(tmp_path):
    _write_fixture(tmp_path, "20260226 - multi.txt", FIXTURE_MULTI_TURN)
    parser = TerminalClaudeCodeParser()
    parser.parse(tmp_path)
    assert len(parser.messages) == 4
    roles = [m.role for m in parser.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert len(parser.events) == 1
    assert parser.events[0].tool_name == "Read"


def test_terminal_no_tools(tmp_path):
    _write_fixture(tmp_path, "20260210 - no tools.txt", FIXTURE_NO_TOOLS)
    parser = TerminalClaudeCodeParser()
    parser.parse(tmp_path)
    assert len(parser.events) == 0
    assert len(parser.messages) == 2


def test_terminal_conversation_id(tmp_path):
    _write_fixture(tmp_path, "20260210 - test session.txt", FIXTURE_SIMPLE)
    parser = TerminalClaudeCodeParser()
    parser.parse(tmp_path)
    assert parser.conversations[0].conversation_id == "manual_terminal_20260210 - test session"


def test_terminal_user_content(tmp_path):
    _write_fixture(tmp_path, "20260210 - test.txt", FIXTURE_SIMPLE)
    parser = TerminalClaudeCodeParser()
    parser.parse(tmp_path)
    user_msg = parser.messages[0]
    assert "qual vault" in user_msg.content
    assert "❯" not in user_msg.content
