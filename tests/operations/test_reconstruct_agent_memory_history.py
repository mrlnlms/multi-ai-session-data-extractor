import json

from src.operations.reconstruct_agent_memory_history import reconstruct


def test_preview_is_pure_and_apply_is_idempotent(tmp_path):
    raw = tmp_path / "raw"
    memory = raw / "memories" / "nested" / "2025-03-04-note.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("Created: 2025-03-03\nbody")

    preview = reconstruct(raw_root=raw, source="codex")
    assert preview["versions_to_seed"] == 1
    assert not (raw / "_memory_metadata.json").exists()
    assert not (raw / "_memory_versions").exists()

    reconstruct(raw_root=raw, source="codex", apply=True)
    first = (raw / "_memory_metadata.json").read_bytes()
    reconstruct(raw_root=raw, source="codex", apply=True)
    assert (raw / "_memory_metadata.json").read_bytes() == first
    payload = json.loads(first)
    version = payload["documents"]["memories/nested/2025-03-04-note.md"]["versions"][0]
    assert (raw / version["raw_path"]).read_text() == memory.read_text()


def test_reconstruction_migrates_v1_mtime_without_inventing_first_seen(tmp_path):
    raw = tmp_path / "raw"
    memory = raw / "memories" / "note.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("body")
    (raw / "_memory_metadata.json").write_text(json.dumps({
        "version": 1, "files": {"memories/note.md": 1_700_000_000_000_000_000},
    }))

    reconstruct(raw_root=raw, source="codex", apply=True)

    payload = json.loads((raw / "_memory_metadata.json").read_text())
    version = payload["documents"]["memories/note.md"]["versions"][0]
    assert version["source_modified_at"] == "2023-11-14T22:13:20Z"
    assert version["first_seen_at"] is None
