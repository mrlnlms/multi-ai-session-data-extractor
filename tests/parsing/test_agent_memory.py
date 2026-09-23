import pytest
import pandas as pd
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from src.capture.cli.memory_metadata import observe_memory_files
from src.parsing.agent_memory import (
    parse_agent_memory_file,
    parse_frontmatter,
    decode_project_path,
    parse_memories_for_source,
    parse_memory_archive,
)


# --- frontmatter parsing ---

def test_frontmatter_valid_yaml():
    content = """---
name: User profile
description: Senior researcher
type: user
---
body content here
"""
    fm, body = parse_frontmatter(content)
    assert fm == {"name": "User profile", "description": "Senior researcher", "type": "user"}
    assert body == "body content here\n"


def test_frontmatter_missing_returns_empty():
    content = "no frontmatter here\njust body"
    fm, body = parse_frontmatter(content)
    assert fm == {}
    assert body == content


def test_frontmatter_malformed_salvages_simple_scalar_metadata():
    content = """---
type: feedback
name: Preference: concise responses
description: Uses colons: safely retained as text
---
body"""
    fm, body = parse_frontmatter(content)
    assert fm == {
        "type": "feedback",
        "name": "Preference: concise responses",
        "description": "Uses colons: safely retained as text",
    }
    assert body == "body"


def test_frontmatter_malformed_without_simple_fields_returns_empty():
    content = """---
not valid: yaml: too: many: colons:
---
body"""
    fm, body = parse_frontmatter(content)
    assert fm == {}
    assert body == content


# --- single file parse ---

def test_parse_user_memory(tmp_path):
    f = tmp_path / "user_profile.md"
    f.write_text("""---
name: User profile
description: Senior researcher
type: user
---
Marlon Lemes.
""")
    m = parse_agent_memory_file(
        path=f, source="claude_code",
        project_path="/Users/x/p", project_key="-Users-x-p",
        is_preserved_missing=False,
    )
    assert m.kind == "user"
    assert m.name == "User profile"
    assert m.description == "Senior researcher"
    assert "Marlon" in m.content
    assert m.file_name == "user_profile.md"
    assert m.memory_id == "claude_code:-Users-x-p/memory/user_profile.md"
    assert m.relative_path == "-Users-x-p/memory/user_profile.md"


def test_parse_memory_md_index_no_frontmatter(tmp_path):
    f = tmp_path / "MEMORY.md"
    f.write_text("# Index\n- [User](user.md)\n")
    m = parse_agent_memory_file(
        path=f, source="claude_code",
        project_path="/Users/x/p", project_key="-Users-x-p",
        is_preserved_missing=False,
    )
    assert m.kind == "index"
    assert m.name is None


def test_parse_memory_invalid_kind_falls_back_to_other(tmp_path):
    f = tmp_path / "weird.md"
    f.write_text("---\ntype: bogus\n---\nbody\n")
    m = parse_agent_memory_file(
        path=f, source="claude_code",
        project_path="/p", project_key="-p",
        is_preserved_missing=False,
    )
    assert m.kind == "other"


def test_parse_memory_no_frontmatter_falls_back_to_other(tmp_path):
    f = tmp_path / "raw.md"
    f.write_text("just text, no frontmatter\n")
    m = parse_agent_memory_file(
        path=f, source="claude_code",
        project_path="/p", project_key="-p",
        is_preserved_missing=False,
    )
    assert m.kind == "other"


def test_parse_codex_memory_null_project(tmp_path):
    f = tmp_path / "global.md"
    f.write_text("---\ntype: feedback\n---\nbody\n")
    m = parse_agent_memory_file(
        path=f, source="codex",
        project_path=None, project_key=None,
        is_preserved_missing=False,
    )
    assert m.kind == "feedback"
    assert m.memory_id == "codex:memories/global.md"


def test_parse_memory_archive_exposes_versions_and_temporal_evidence(tmp_path):
    source = tmp_path / ".codex"
    memory = source / "memories" / "2025-04-03-notes.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("---\ncreated_at: 2025-04-02T10:00:00Z\n---\nbody")
    raw = tmp_path / "raw"
    observe_memory_files(
        raw, source, "codex", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    result = parse_memory_archive(raw, "codex", {"memories/2025-04-03-notes.md"})

    assert len(result.memories) == len(result.versions) == 1
    memory_row = result.memories[0]
    version = result.versions[0]
    assert memory_row.current_version_id == version.version_id
    assert version.created_at_basis == "explicit_structured_timestamp"
    assert version.created_at_confidence == "high"
    assert {item.evidence_type for item in result.temporal_evidence} >= {
        "explicit_structured_timestamp", "first_observed", "source_mtime",
        "filename_timestamp",
    }
    assert len({item.evidence_id for item in result.temporal_evidence}) == len(
        result.temporal_evidence
    )


# --- decode_project_path ---

def test_decode_project_path_from_jsonl_cwd(tmp_path):
    proj = tmp_path / "-Users-x-Desktop-multi-ai-session-data-extractor"
    proj.mkdir()
    jsonl = proj / "fake-session.jsonl"
    jsonl.write_text(
        '{"type":"summary","sessionId":"x"}\n'
        '{"type":"attachment","cwd":"/Users/x/Desktop/multi-ai-session-data-extractor"}\n'
    )
    path = decode_project_path(proj)
    assert path == "/Users/x/Desktop/multi-ai-session-data-extractor"


def test_decode_project_path_no_jsonl_returns_none(tmp_path):
    proj = tmp_path / "-some-encoded"
    proj.mkdir()
    assert decode_project_path(proj) is None


# --- batch parse for source ---

def test_parse_memories_claude_code_per_project(tmp_path):
    raw_root = tmp_path / "Claude Code"
    raw_root.mkdir()
    proj = raw_root / "-Users-x-proj"
    proj.mkdir()
    # jsonl de stub pra cwd resolution
    (proj / "session.jsonl").write_text('{"type":"attachment","cwd":"/Users/x/proj"}\n')
    mem = proj / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_text("# index\n")
    (mem / "user_profile.md").write_text("---\ntype: user\nname: U\n---\nbody")
    (mem / "feedback_x.md").write_text("---\ntype: feedback\nname: F\n---\nbody")

    home_files = {"-Users-x-proj/memory/MEMORY.md", "-Users-x-proj/memory/user_profile.md"}
    items = parse_memories_for_source(raw_root, "claude_code", home_files)
    by_name = {m.file_name: m for m in items}
    assert "MEMORY.md" in by_name
    assert by_name["MEMORY.md"].kind == "index"
    assert by_name["user_profile.md"].kind == "user"
    assert by_name["feedback_x.md"].kind == "feedback"
    assert by_name["feedback_x.md"].is_preserved_missing is True
    assert by_name["user_profile.md"].is_preserved_missing is False
    assert all(m.project_path == "/Users/x/proj" for m in items)


def test_parse_memories_uses_manifest_timestamp_instead_of_raw_mtime(tmp_path):
    raw_root = tmp_path / "Claude Code"
    memory = raw_root / "-Users-x-proj" / "memory" / "MEMORY.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("# index\n")
    os.utime(memory, ns=(900_000_000_000, 900_000_000_000))
    timestamp_ns = 123_456_789_000
    (raw_root / "_memory_metadata.json").write_text(json.dumps({
        "version": 1,
        "files": {"-Users-x-proj/memory/MEMORY.md": timestamp_ns},
    }))

    [item] = parse_memories_for_source(raw_root, "claude_code", set())

    expected = pd.Timestamp(timestamp_ns, unit="ns", tz="UTC")
    assert item.created_at == expected
    assert item.updated_at == expected


def test_parse_memories_without_manifest_falls_back_to_raw_mtime(tmp_path):
    raw_root = tmp_path / "Codex"
    memory = raw_root / "memories" / "global.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("# memory\n")
    timestamp_ns = 234_567_890_000
    os.utime(memory, ns=(timestamp_ns, timestamp_ns))

    [item] = parse_memories_for_source(raw_root, "codex", set())

    assert item.updated_at == pd.Timestamp(timestamp_ns, unit="ns", tz="UTC")


def test_parse_memories_codex_global_dir(tmp_path):
    raw_root = tmp_path / "Codex"
    raw_root.mkdir()
    mem = raw_root / "memories"
    mem.mkdir()
    (mem / "global_a.md").write_text("---\ntype: project\n---\nbody")
    items = parse_memories_for_source(raw_root, "codex", set())
    assert len(items) == 1
    assert items[0].project_path is None
    assert items[0].is_preserved_missing is True


def test_parse_memories_empty_source_returns_empty(tmp_path):
    raw_root = tmp_path / "Codex"
    raw_root.mkdir()
    items = parse_memories_for_source(raw_root, "codex", set())
    assert items == []


def test_parse_memories_unknown_source_raises():
    with pytest.raises(ValueError):
        parse_memories_for_source(Path("/tmp"), "unknown", set())


def test_parse_memories_skips_unreadable_file_and_continues(tmp_path):
    """Um arquivo .md corrompido nao aborta o batch — apenas loga warning e segue."""
    raw_root = tmp_path / "Codex"
    raw_root.mkdir()
    mem = raw_root / "memories"
    mem.mkdir()
    # Arquivo valido
    (mem / "good.md").write_text("---\ntype: user\n---\nbody")
    # Arquivo com bytes nao-UTF8 (vai quebrar read_text com encoding utf-8)
    (mem / "bad.md").write_bytes(b"\xff\xfe\x00invalid utf-8 bytes\xc0\xc1")

    items = parse_memories_for_source(raw_root, "codex", set())
    # bad.md eh skipped, good.md eh ingerido
    file_names = {m.file_name for m in items}
    assert "good.md" in file_names
    assert "bad.md" not in file_names
