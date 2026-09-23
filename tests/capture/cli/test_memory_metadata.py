import json
import os
from datetime import datetime, timezone

from src.capture.cli.memory_metadata import (
    MANIFEST_NAME,
    load_memory_manifest,
    load_memory_metadata,
    observe_memory_files,
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
    assert payload["version"] == 2
    document = payload["documents"]["-Users-x-proj/memory/MEMORY.md"]
    assert document["is_present"] is True
    assert document["versions"][0]["source_modified_at"] == "1970-01-01T00:02:03.456789Z"
    assert (raw / document["versions"][0]["raw_path"]).read_text() == "# memory"


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


def test_observation_retains_changed_and_missing_versions(tmp_path):
    source = tmp_path / ".codex"
    memory = source / "memories" / "nested" / "same.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("first")
    raw = tmp_path / "raw"
    first_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second_time = datetime(2026, 1, 2, tzinfo=timezone.utc)

    observe_memory_files(raw, source, "codex", first_time)
    memory.write_text("second")
    observe_memory_files(raw, source, "codex", second_time)
    memory.unlink()
    observe_memory_files(raw, source, "codex", datetime(2026, 1, 3, tzinfo=timezone.utc))

    document = load_memory_manifest(raw).documents["memories/nested/same.md"]
    assert document["is_present"] is False
    assert len(document["versions"]) == 2
    assert len(list((raw / "_memory_versions").glob("*.md"))) == 2


def test_full_relative_path_avoids_basename_collision(tmp_path):
    source = tmp_path / ".codex"
    for folder in ("one", "two"):
        path = source / "memories" / folder / "same.md"
        path.parent.mkdir(parents=True)
        path.write_text(folder)

    manifest = observe_memory_files(
        tmp_path / "raw", source, "codex", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert set(manifest.documents) == {
        "memories/one/same.md", "memories/two/same.md",
    }


def test_gemini_memory_metadata_uses_projected_paths(tmp_path):
    raw = tmp_path / "raw"
    memory = raw / "_agent_memory" / "global" / "GEMINI.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("# global", encoding="utf-8")

    manifest = observe_memory_files(raw, raw, "gemini_cli")

    assert set(manifest.documents) == {"_agent_memory/global/GEMINI.md"}
