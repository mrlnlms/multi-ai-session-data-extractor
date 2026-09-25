"""Qwen account-memory capture and canonical replay boundaries."""

import asyncio
import hashlib
import json

import pytest

from src.platforms.qwen.extractor.account_memory import capture_account_memory
from src.platforms.qwen.extractor.api_client import QwenAPIClient
from src.platforms.qwen.memory_parser import parse_account_memory


ACCOUNT_ID = "810f3e91-ae10-5cb1-931a-53b80630af16"


def _node(index, content=None):
    return {
        "memory_node_id": f"native-{index}", "content": content or f"fact {index}",
        "chat_id": f"chat-{index}", "created_at": 1_760_000_000,
        "updated_at": 1_760_000_100,
    }


class _Client:
    def __init__(self, nodes, *, personalization=None, fail_page=None):
        self.nodes = nodes
        self.personalization = personalization
        self.fail_page = fail_page
        self.pages = []

    async def list_memory_page(self, page_num, page_size=50):
        self.pages.append(page_num)
        if page_num == self.fail_page:
            raise RuntimeError("private upstream error")
        start = (page_num - 1) * page_size
        return {"success": True, "data": {
            "memory_nodes": self.nodes[start:start + page_size], "total": len(self.nodes),
        }}

    async def get_user_settings(self):
        data = {"memory": {"enable_memory": True}}
        if self.personalization is not None:
            data["personalization"] = self.personalization
        return {"success": True, "data": data}


class _NullPersonalizationClient(_Client):
    async def get_user_settings(self):
        return {"success": True, "data": {
            "memory": {"enable_memory": True}, "personalization": None,
        }}


def test_paginated_capture_has_hashes_and_separate_personalization(tmp_path):
    nodes = [_node(i) for i in range(51)]
    client = _Client(nodes, personalization={
        "name": "Test", "description": "", "instruction": "Be concise",
        "style": None, "enable_for_new_chat": True,
    })
    result = asyncio.run(capture_account_memory(client, tmp_path))
    assert client.pages == [1, 2]
    assert result["saved_memories"]["items"] == 51
    assert result["personalization"]["complete"]
    for surface in result.values():
        manifest = json.loads((surface["snapshot"] / "capture.json").read_text())
        assert manifest["complete"]
        for name, info in manifest["files"].items():
            assert hashlib.sha256((surface["snapshot"] / name).read_bytes()).hexdigest() == info["sha256"]
    parsed = parse_account_memory(tmp_path, ACCOUNT_ID)
    assert len(parsed.memories) == 52
    assert len(parsed.versions) == 52
    assert {m.kind for m in parsed.memories} == {"saved_memory", "account_instructions"}
    assert all(m.account_id == ACCOUNT_ID and m.project_key is None for m in parsed.memories)
    saved = next(m for m in parsed.memories if m.memory_id.endswith("native-50"))
    assert saved.content == "fact 50"
    assert saved.created_at.year == 2025
    assert any(e.evidence_type == "native_created_at" for e in parsed.temporal_evidence)


def test_partial_page_never_marks_missing_but_complete_empty_does(tmp_path):
    asyncio.run(capture_account_memory(_Client([_node(i) for i in range(51)]), tmp_path))
    partial = asyncio.run(capture_account_memory(
        _Client([_node(i) for i in range(51)], fail_page=2), tmp_path,
    ))
    assert not partial["saved_memories"]["complete"]
    assert (partial["saved_memories"]["snapshot"] / "pages/0001.json").exists()
    assert "private upstream error" not in (partial["saved_memories"]["snapshot"] / "capture.json").read_text()
    assert all(not m.is_preserved_missing for m in parse_account_memory(tmp_path, ACCOUNT_ID).memories)

    asyncio.run(capture_account_memory(_Client([]), tmp_path))
    parsed = parse_account_memory(tmp_path, ACCOUNT_ID)
    assert len(parsed.memories) == 51
    assert all(m.is_preserved_missing for m in parsed.memories)


def test_content_versions_and_personalization_disappearance(tmp_path):
    first = _Client([_node(1, "old")], personalization={"instruction": "First", "enable_for_new_chat": True})
    second = _Client([_node(1, "new")])
    asyncio.run(capture_account_memory(first, tmp_path))
    asyncio.run(capture_account_memory(second, tmp_path))
    parsed = parse_account_memory(tmp_path, ACCOUNT_ID)
    saved = next(m for m in parsed.memories if m.kind == "saved_memory")
    instruction = next(m for m in parsed.memories if m.kind == "account_instructions")
    assert saved.content == "new" and not saved.is_preserved_missing
    assert instruction.is_preserved_missing
    assert len([v for v in parsed.versions if v.memory_id == saved.memory_id]) == 2


def test_explicit_null_personalization_is_complete_empty_state(tmp_path):
    result = asyncio.run(capture_account_memory(_NullPersonalizationClient([]), tmp_path))
    assert result["personalization"]["complete"]
    assert parse_account_memory(tmp_path, ACCOUNT_ID).memories == []


def test_hash_corruption_rejected(tmp_path):
    result = asyncio.run(capture_account_memory(_Client([_node(1)]), tmp_path))
    page = result["saved_memories"]["snapshot"] / "pages/0001.json"
    page.write_text("{}")
    with pytest.raises(ValueError, match="hash or path"):
        parse_account_memory(tmp_path, ACCOUNT_ID)


def test_api_uses_observed_read_only_routes():
    client = QwenAPIClient(None, None)
    paths = []

    async def fake_fetch(path, method="GET"):
        paths.append((method, path))
        return {}

    client._fetch = fake_fetch

    async def run():
        await client.list_memory_page(3)
        await client.get_user_settings()

    asyncio.run(run())
    assert paths == [
        ("GET", "https://chat.qwen.ai/api/v2/memories/?page_size=50&page_num=3"),
        ("GET", "https://chat.qwen.ai/api/v2/users/user/settings"),
    ]
