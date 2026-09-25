"""Claude topic capture and canonical replay use native identity and scope."""

import asyncio
import pytest

from src.platforms.claude_ai.extractor.account_memory import capture_account_memory
from src.platforms.claude_ai.memory_parser import parse_account_memory


ACCOUNT_ID = "c82fa08b-228f-58a6-bf5d-003e816ada41"
PROJECT_ID = "01998bf0-4bad-7466-ba23-97b6bd7e995c"


def _entry(native_id, path, category):
    return {"memory_id": native_id, "path": path, "category_id": category,
            "display_name": "Topic", "description": "Summary", "updated_at": "2026-09-20T10:00:00Z"}


class _Client:
    def __init__(self, entries, contents, fail_path=None, mode="melange"):
        self.entries = entries
        self.contents = contents
        self.fail_path = fail_path
        self.mode = mode

    async def list_memory_topics(self):
        return {"data": self.entries, "categories": []}

    async def read_memory_topic(self, path):
        if path == self.fail_path:
            raise RuntimeError("private upstream body must not enter logs")
        return {"path": path, "content": self.contents[path], "updated_at": "2026-09-20T10:00:00Z",
                "version": "v1", "parsed": {"body": self.contents[path]}}

    async def get_memory_settings(self):
        return {"memory_mode": self.mode}


def test_capture_and_replay_preserves_project_scope_versions_and_missing(tmp_path):
    account = _entry("mem_account", "/you/profile", "you")
    project = _entry("mem_project", f"/projects/{PROJECT_ID}/overview", "projects")
    first = _Client([account, project], {account["path"]: "profile v1", project["path"]: "project v1"})
    result = asyncio.run(capture_account_memory(first, tmp_path))
    assert result["complete"] and result["topics"] == 2

    second = _Client([account], {account["path"]: "profile v2"})
    assert asyncio.run(capture_account_memory(second, tmp_path))["complete"]
    parsed = parse_account_memory(tmp_path, ACCOUNT_ID)
    assert len(parsed.memories) == 2
    by_kind = {memory.kind: memory for memory in parsed.memories}
    assert by_kind["project_memory"].project_key == PROJECT_ID
    assert by_kind["project_memory"].is_preserved_missing
    assert by_kind["saved_memory"].content == "profile v2"
    assert len(parsed.versions) == 3
    assert all(version.account_id == ACCOUNT_ID for version in parsed.versions)
    assert all(evidence.locator for evidence in parsed.temporal_evidence)


def test_incomplete_capture_does_not_mark_prior_topics_missing(tmp_path):
    item = _entry("mem_one", "/you/profile", "you")
    asyncio.run(capture_account_memory(_Client([item], {item["path"]: "saved"}), tmp_path))
    failed = asyncio.run(capture_account_memory(_Client([item], {}, fail_path=item["path"]), tmp_path))
    assert not failed["complete"] and failed["failed_reads"] == 1
    [memory] = parse_account_memory(tmp_path, ACCOUNT_ID).memories
    assert memory.content == "saved"
    assert not memory.is_preserved_missing


def test_mode_change_cannot_turn_empty_list_into_deletion(tmp_path):
    item = _entry("mem_one", "/you/profile", "you")
    asyncio.run(capture_account_memory(_Client([item], {item["path"]: "saved"}), tmp_path))
    changed_mode = asyncio.run(capture_account_memory(_Client([], {}, mode="classic"), tmp_path))
    assert not changed_mode["complete"]
    [memory] = parse_account_memory(tmp_path, ACCOUNT_ID).memories
    assert not memory.is_preserved_missing


def test_complete_empty_list_marks_known_topics_missing_without_deleting_them(tmp_path):
    item = _entry("mem_one", "/you/profile", "you")
    asyncio.run(capture_account_memory(_Client([item], {item["path"]: "saved"}), tmp_path))
    assert asyncio.run(capture_account_memory(_Client([], {}), tmp_path))["complete"]
    [memory] = parse_account_memory(tmp_path, ACCOUNT_ID).memories
    assert memory.is_preserved_missing
    assert memory.content == "saved"


def test_corrupt_complete_snapshot_fails_loudly(tmp_path):
    item = _entry("mem_one", "/you/profile", "you")
    result = asyncio.run(capture_account_memory(_Client([item], {item["path"]: "saved"}), tmp_path))
    (result["snapshot"] / "list.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        parse_account_memory(tmp_path, ACCOUNT_ID)


def test_legacy_markdown_remains_opaque_and_undated(tmp_path):
    (tmp_path / "claude_ai_memory.md").write_text("# Preferences\n- A memory")
    [memory] = parse_account_memory(tmp_path, ACCOUNT_ID).memories
    assert memory.kind == "legacy_export"
    assert memory.created_at is None
    assert memory.content == "# Preferences\n- A memory"
