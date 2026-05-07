import json
from pathlib import Path
import pytest
from src.extractors.cli.snapshot import collect_files_for_snapshot


def test_collect_claude_code_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    claude = home / ".claude"
    claude.mkdir()
    (claude / "CLAUDE.md").write_text("# global instructions")
    (claude / "settings.json").write_text(json.dumps({"env": {"K": "v"}}))
    (claude / "settings.local.json").write_text(json.dumps({"local": True}))
    (claude / "statusline-command.sh").write_text("#!/bin/sh\necho hi")
    (claude / "skills").mkdir()
    (claude / "skills" / "my-skill.md").write_text("skill content")
    (claude / "commands").mkdir()
    (claude / "commands" / "my-cmd.md").write_text("cmd content")
    (claude / "hooks").mkdir()
    (claude / "hooks" / "tsc-check.sh").write_text("#!/bin/sh")
    (claude / "cache").mkdir()  # excluded
    (claude / "cache" / "junk.bin").write_text("junk")

    files = collect_files_for_snapshot("claude_code")
    rels = sorted(files.keys())
    assert "CLAUDE.md" in rels
    assert "settings.json" in rels
    assert "settings.local.json" in rels
    assert "statusline-command.sh" in rels
    assert "skills/my-skill.md" in rels
    assert "commands/my-cmd.md" in rels
    assert "hooks/tsc-check.sh" in rels
    assert "cache/junk.bin" not in rels


def test_collect_codex_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    codex = home / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text("[core]\n")
    (codex / "version.json").write_text("{}")
    (codex / "installation_id").write_text("uuid-xxx")
    (codex / "models_cache.json").write_text("{}")
    (codex / ".codex-global-state.json").write_text("{}")
    (codex / "rules").mkdir()
    (codex / "rules" / "default.rules").write_text("rule content")
    (codex / "auth.json").write_text('{"refresh_token": "secret"}')  # excluded
    (codex / "memories").mkdir()
    (codex / "memories" / "x.md").write_text("memory")  # excluded (canonical)
    (codex / "logs_2.sqlite").write_bytes(b"\x00")  # excluded

    files = collect_files_for_snapshot("codex")
    rels = sorted(files.keys())
    assert "config.toml" in rels
    assert "rules/default.rules" in rels
    assert "auth.json" not in rels
    assert "memories/x.md" not in rels  # canonical entity, not snapshot
    assert "logs_2.sqlite" not in rels


def test_collect_gemini_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    gem = home / ".gemini"
    gem.mkdir()
    (gem / "settings.json").write_text("{}")
    (gem / "projects.json").write_text("{}")
    (gem / "state.json").write_text("{}")
    (gem / "trustedFolders.json").write_text("[]")
    (gem / "installation_id").write_text("uuid")
    (gem / "oauth_creds.json").write_text("{}")  # excluded
    (gem / "google_accounts.json").write_text("{}")  # excluded

    files = collect_files_for_snapshot("gemini")
    rels = sorted(files.keys())
    assert "settings.json" in rels
    assert "projects.json" in rels
    assert "trustedFolders.json" in rels
    assert "oauth_creds.json" not in rels
    assert "google_accounts.json" not in rels
