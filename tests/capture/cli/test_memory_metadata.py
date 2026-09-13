import json
import os

from src.capture.cli.memory_metadata import (
    MANIFEST_NAME,
    load_memory_metadata,
    update_memory_metadata,
)


def test_update_claude_memory_metadata_records_source_mtime_ns(tmp_path):
    source = tmp_path / "projects"
    memory = source / "-Users-x-proj" / "memory" / "MEMORY.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("# memory")
    os.utime(memory, ns=(123_456_789_000, 123_456_789_000))
    raw = tmp_path / "raw"

    metadata = update_memory_metadata(raw, source, "claude_code")

    assert metadata == {"-Users-x-proj/memory/MEMORY.md": 123_456_789_000}
    payload = json.loads((raw / MANIFEST_NAME).read_text())
    assert payload == {"version": 1, "files": metadata}


def test_update_memory_metadata_retains_missing_source_entries(tmp_path):
    source = tmp_path / "projects"
    source.mkdir()
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / MANIFEST_NAME).write_text(
        json.dumps({"version": 1, "files": {"gone/memory/old.md": 42}})
    )

    metadata = update_memory_metadata(raw, source, "claude_code")

    assert metadata == {"gone/memory/old.md": 42}
    assert load_memory_metadata(raw) == metadata


def test_update_codex_memory_metadata_uses_memories_prefix(tmp_path):
    source = tmp_path / ".codex"
    memory = source / "memories" / "global.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("# memory")
    raw = tmp_path / "raw"

    metadata = update_memory_metadata(raw, source, "codex")

    assert set(metadata) == {"memories/global.md"}
