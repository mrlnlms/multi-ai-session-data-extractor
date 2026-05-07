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


from src.extractors.cli.snapshot import snapshot_configs


def _setup_minimal_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").write_text("instructions v1")
    (home / ".claude" / "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_API_KEY": "sk-xx"}}))
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text("[core]\nv=1")
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text("{}")
    return home


def test_snapshot_first_run_creates_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.extractors.cli.snapshot.EXTERNAL", tmp_path / "external")
    home = _setup_minimal_home(tmp_path, monkeypatch)

    snapshot_configs()

    cc_root = tmp_path / "external" / "claude-code-config-snapshots"
    assert cc_root.exists()
    snapshot_dirs = list(cc_root.iterdir())
    assert len(snapshot_dirs) == 1
    snap = snapshot_dirs[0]
    assert (snap / "CLAUDE.md").read_text() == "instructions v1"
    settings = json.loads((snap / "settings.json").read_text())
    assert settings["env"]["ANTHROPIC_API_KEY"] == "<redacted>"
    meta = json.loads((snap / "_meta.json").read_text())
    assert "captured_at" in meta
    assert "content_hash" in meta


def test_snapshot_idempotent_no_op_on_second_run(tmp_path, monkeypatch):
    monkeypatch.setattr("src.extractors.cli.snapshot.EXTERNAL", tmp_path / "external")
    _setup_minimal_home(tmp_path, monkeypatch)

    snapshot_configs()
    cc_root = tmp_path / "external" / "claude-code-config-snapshots"
    first_dirs = sorted(p.name for p in cc_root.iterdir())

    snapshot_configs()  # no change in source
    second_dirs = sorted(p.name for p in cc_root.iterdir())

    assert first_dirs == second_dirs  # no new snapshot


def test_snapshot_creates_new_when_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr("src.extractors.cli.snapshot.EXTERNAL", tmp_path / "external")
    home = _setup_minimal_home(tmp_path, monkeypatch)

    snapshot_configs()
    cc_root = tmp_path / "external" / "claude-code-config-snapshots"
    first = list(cc_root.iterdir())
    assert len(first) == 1

    (home / ".claude" / "CLAUDE.md").write_text("instructions v2")  # change
    snapshot_configs()

    second = list(cc_root.iterdir())
    assert len(second) == 2
