"""Tests pra cli-copy memory/* extension (C3)."""
import os
import pytest
import sqlite3
from pathlib import Path
from src.capture.cli.copy import (
    _sync_tree,
    copy_antigravity_cli,
    copy_codex_memories,
    copy_claude_code,
    current_source_files,
    SOURCES,
    copy_gemini_cli_memories,
    RAW,
)


def test_sync_tree_skips_macos_finder_metadata(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / ".DS_Store").write_bytes(b"finder metadata")
    (source / "session.json").write_text("{}")

    result = _sync_tree(source, destination)

    assert [path.name for path in result["new"]] == ["session.json"]
    assert not (destination / ".DS_Store").exists()


def test_sync_tree_updates_different_content_when_raw_mtime_is_newer(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    live = source / "session.jsonl"
    raw = destination / "session.jsonl"
    live.write_text("complete live session", encoding="utf-8")
    raw.write_text("older", encoding="utf-8")
    os.utime(live, ns=(100, 100))
    os.utime(raw, ns=(200, 200))

    result = _sync_tree(source, destination)

    assert result["updated"] == [raw]
    assert raw.read_text(encoding="utf-8") == "complete live session"


def test_sync_tree_new_file_is_independent_copy(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    live = source / "session.jsonl"
    live.write_text("first", encoding="utf-8")

    _sync_tree(source, destination)
    live.write_text("mutated later", encoding="utf-8")

    assert (destination / "session.jsonl").read_text(encoding="utf-8") == "first"


def test_copy_codex_memories_no_op_when_src_missing(tmp_path, monkeypatch):
    """Sem ~/.codex/memories/, retorna empty no-op."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = copy_codex_memories()
    assert result == {"new": [], "updated": []}


def test_copy_gemini_cli_memories_discovers_global_and_project_context(tmp_path, monkeypatch):
    gemini_home = tmp_path / ".gemini"
    source = gemini_home / "tmp"
    destination = tmp_path / "raw" / "Gemini CLI"
    project = tmp_path / "project"
    source_project = source / "project-key"
    source_project.mkdir(parents=True)
    project.mkdir()
    (source_project / ".project_root").write_text(str(project), encoding="utf-8")
    (gemini_home / "settings.json").write_text(
        '{"context":{"fileName":["AGENTS.md","GEMINI.md"]}}', encoding="utf-8"
    )
    (gemini_home / "GEMINI.md").write_text("global", encoding="utf-8")
    (project / "AGENTS.md").write_text("project", encoding="utf-8")
    monkeypatch.setitem(SOURCES, "gemini_cli", {
        "src": source, "dst": destination, "label": "Gemini CLI",
    })

    result = copy_gemini_cli_memories()

    assert len(result["new"]) == 2
    assert (destination / "_agent_memory/global/GEMINI.md").read_text() == "global"
    assert (
        destination / "_agent_memory/projects/project-key/AGENTS.md"
    ).read_text() == "project"
    assert set(current_source_files("gemini_cli")) >= {
        "_agent_memory/global/GEMINI.md",
        "_agent_memory/projects/project-key/AGENTS.md",
    }


def test_copy_codex_memories_copies_new_files(tmp_path, monkeypatch):
    """Arquivos .md novos viram entries em 'new'."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("src.capture.cli.copy.RAW", tmp_path / "raw")
    src = tmp_path / ".codex" / "memories"
    src.mkdir(parents=True)
    (src / "global_a.md").write_text("---\ntype: feedback\n---\nbody")
    (src / "global_b.md").write_text("---\ntype: project\n---\nbody")

    result = copy_codex_memories()
    assert len(result["new"]) == 2
    assert len(result["updated"]) == 0
    dst = tmp_path / "raw" / "Codex" / "memories"
    assert (dst / "global_a.md").exists()
    assert (dst / "global_b.md").exists()


def test_copy_claude_code_includes_memory_files(tmp_path, monkeypatch):
    """copy_claude_code copia memory/*.md per project."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Tem que reapontar SOURCES porque ele foi computado at import time
    monkeypatch.setitem(SOURCES, "claude_code", {
        "src": tmp_path / ".claude" / "projects",
        "dst": tmp_path / "raw" / "Claude Code",
        "label": "Claude Code",
    })
    src = tmp_path / ".claude" / "projects"
    proj = src / "-Users-x-proj"
    proj.mkdir(parents=True)
    # session jsonl pra evidenciar que memory eh extra (nao substitui)
    (proj / "session.jsonl").write_text('{"type":"summary"}')
    mem = proj / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_text("# index")
    (mem / "user_profile.md").write_text("---\ntype: user\n---\nbody")

    result = copy_claude_code()
    new_paths = {str(p) for p in result["new"]}
    # session.jsonl + 2 memory files = 3 novos
    assert any("session.jsonl" in p for p in new_paths)
    assert any("MEMORY.md" in p for p in new_paths)
    assert any("user_profile.md" in p for p in new_paths)
    assert (tmp_path / "raw" / "Claude Code" / "_memory_metadata.json").is_file()


def test_current_source_files_codex_includes_memories_prefix(tmp_path, monkeypatch):
    """current_source_files('codex') retorna paths de memories/ prefixados."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setitem(SOURCES, "codex", {
        "src": tmp_path / ".codex" / "sessions",
        "dst": tmp_path / "raw" / "Codex",
        "label": "Codex",
    })
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "2026").mkdir()
    (sessions / "2026" / "rollout-test.jsonl").write_text("{}")

    memories = tmp_path / ".codex" / "memories"
    memories.mkdir(parents=True)
    (memories / "global.md").write_text("---\ntype: feedback\n---\nbody")

    result = current_source_files("codex")
    # Sessions paths NAO levam prefixo memories/
    assert any(p.endswith("rollout-test.jsonl") and not p.startswith("memories/") for p in result)
    # Memory paths LEVAM prefixo memories/
    assert "memories/global.md" in result


def test_current_source_files_claude_code_includes_memory(tmp_path, monkeypatch):
    """current_source_files('claude_code') retorna paths jsonl + memory/ paths."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setitem(SOURCES, "claude_code", {
        "src": tmp_path / ".claude" / "projects",
        "dst": tmp_path / "raw" / "Claude Code",
        "label": "Claude Code",
    })
    src = tmp_path / ".claude" / "projects"
    proj = src / "-Users-x-proj"
    proj.mkdir(parents=True)
    (proj / "session.jsonl").write_text("{}")
    mem = proj / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_text("# index")

    result = current_source_files("claude_code")
    assert "-Users-x-proj/session.jsonl" in result
    assert "-Users-x-proj/memory/MEMORY.md" in result


def test_copy_antigravity_cli_copies_selected_conversation_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    source = tmp_path / ".gemini" / "antigravity-cli"
    destination = tmp_path / "raw" / "Antigravity CLI"
    monkeypatch.setitem(SOURCES, "antigravity_cli", {
        "src": source, "dst": destination, "label": "Antigravity CLI",
    })
    conversations = source / "conversations"
    conversations.mkdir(parents=True)
    db = conversations / "conv.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE steps (id INTEGER)")
    (conversations / "legacy.pb").write_bytes(b"legacy")
    transcript = source / "brain" / "conv" / ".system_generated" / "logs"
    transcript.mkdir(parents=True)
    (transcript / "transcript.jsonl").write_text('{"type":"USER_INPUT"}\n')
    (source / "cache").mkdir()
    (source / "cache" / "conversation_metadata.json").write_text("{}")

    result = copy_antigravity_cli()
    assert len(result["new"]) == 4
    assert (destination / "conversations" / "conv.db").exists()
    assert (destination / "conversations" / "legacy.pb").read_bytes() == b"legacy"
    assert (destination / "brain" / "conv" / ".system_generated" / "logs" / "transcript.jsonl").exists()
    assert not (destination / "settings.json").exists()

    current = current_source_files("antigravity_cli")
    assert "conversations/conv.db" in current
    assert "conversations/legacy.pb" in current
    assert "brain/conv/.system_generated/logs/transcript.jsonl" in current
