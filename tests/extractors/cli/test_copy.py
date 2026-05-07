"""Tests pra cli-copy memory/* extension (C3)."""
import pytest
from pathlib import Path
from src.extractors.cli.copy import (
    copy_codex_memories,
    copy_claude_code,
    current_source_files,
    SOURCES,
    RAW,
)


def test_copy_codex_memories_no_op_when_src_missing(tmp_path, monkeypatch):
    """Sem ~/.codex/memories/, retorna empty no-op."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = copy_codex_memories()
    assert result == {"new": [], "updated": []}


def test_copy_codex_memories_copies_new_files(tmp_path, monkeypatch):
    """Arquivos .md novos viram entries em 'new'."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("src.extractors.cli.copy.RAW", tmp_path / "raw")
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
