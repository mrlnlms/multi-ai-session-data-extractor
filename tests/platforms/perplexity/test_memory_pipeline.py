"""Native account Memory preservation and versioned replay."""

import asyncio
import json

import pytest

from src.platforms.perplexity.extractor.account_memory import capture_account_memory
from src.platforms.perplexity.extractor.api_client import MEMORY_QUERY_HASH, PerplexityAPIClient
from src.platforms.perplexity.memory_parser import parse_account_memory


ACCOUNT_ID = "b879deb4-1c6e-59ad-af3a-fdd06bd6aa95"


def _node(native_id: str, value: str, updated="2026-09-25T10:00:00Z") -> dict:
    return {"__typename": "MemoryItem", "id": native_id, "name": value,
            "categoryId": "individual:memories", "updatedAt": updated,
            "memoryKey": "notes/work", "displayKey": "notes/work",
            "displayKeyPretty": "Work", "displayValue": value,
            "sourceConversations": [{"id": "opaque-source"}]}


def _response(nodes: list[dict], *, more=False, cursor="cursor-1", status="OK") -> dict:
    return {"data": {"viewer": {"knowledgeContext": {"scopeByKind": {
        "id": "individual-scope", "memoryCategories": [{
            "id": "individual:memories", "items": {"status": status,
                "edges": [{"node": node} for node in nodes],
                "pageInfo": {"hasNextPage": more, "endCursor": cursor}},
        }],
    }}}}}


class _Client:
    def __init__(self, pages: list[dict], fail_at: int | None = None):
        self.pages = pages
        self.fail_at = fail_at
        self.cursors = []

    async def list_account_memory_page(self, after=None):
        index = len(self.cursors)
        self.cursors.append(after)
        if index == self.fail_at:
            raise RuntimeError("private upstream body should not appear in logs")
        return self.pages[index]


def test_capture_replay_versions_and_preserved_missing(tmp_path):
    first = _Client([_response([_node("native-1", "v1")], more=True),
                     _response([_node("native-2", "other")])])
    result = asyncio.run(capture_account_memory(first, tmp_path))
    assert result["complete"] and result["items"] == 2 and result["pages"] == 2
    assert first.cursors == [None, "cursor-1"]

    second = _Client([_response([_node("native-1", "v2")])])
    assert asyncio.run(capture_account_memory(second, tmp_path))["complete"]
    parsed = parse_account_memory(tmp_path, ACCOUNT_ID)
    assert len(parsed.memories) == 2 and len(parsed.versions) == 3
    by_id = {memory.memory_id: memory for memory in parsed.memories}
    assert by_id[f"perplexity:{ACCOUNT_ID}:native-1"].content == "v2"
    assert by_id[f"perplexity:{ACCOUNT_ID}:native-2"].is_preserved_missing
    assert all(memory.account_id == ACCOUNT_ID and memory.kind == "saved_memory"
               for memory in parsed.memories)
    assert all("#/response/data/viewer/knowledgeContext/" in e.locator for e in parsed.temporal_evidence)
    locator = by_id[f"perplexity:{ACCOUNT_ID}:native-1"].relative_path
    relative, pointer = locator.split("#", 1)
    node = json.loads((tmp_path / relative).read_text())
    for segment in pointer.strip("/").split("/"):
        node = node[int(segment)] if isinstance(node, list) else node[segment]
    assert node["displayValue"] == "v2"


def test_incomplete_pagination_cannot_mark_prior_memory_missing(tmp_path):
    asyncio.run(capture_account_memory(_Client([_response([_node("native-1", "v1")])]), tmp_path))
    incomplete = _Client([_response([], more=True)], fail_at=1)
    result = asyncio.run(capture_account_memory(incomplete, tmp_path))
    assert not result["complete"] and result["pages"] == 1
    [memory] = parse_account_memory(tmp_path, ACCOUNT_ID).memories
    assert not memory.is_preserved_missing


def test_complete_empty_collection_preserves_previous_as_missing(tmp_path):
    asyncio.run(capture_account_memory(_Client([_response([_node("native-1", "v1")])]), tmp_path))
    assert asyncio.run(capture_account_memory(_Client([_response([])]), tmp_path))["complete"]
    [memory] = parse_account_memory(tmp_path, ACCOUNT_ID).memories
    assert memory.is_preserved_missing and memory.content == "v1"


def test_graphql_error_and_non_ok_status_are_incomplete(tmp_path):
    graphql_error = _response([])
    graphql_error["errors"] = [{"message": "private"}]
    assert not asyncio.run(capture_account_memory(_Client([graphql_error]), tmp_path))["complete"]
    assert not asyncio.run(capture_account_memory(_Client([_response([], status="LOADING")]), tmp_path))["complete"]
    assert parse_account_memory(tmp_path, ACCOUNT_ID).memories == []


def test_corrupt_complete_snapshot_fails_loudly(tmp_path):
    result = asyncio.run(capture_account_memory(_Client([_response([_node("native-1", "v1")])]), tmp_path))
    (result["snapshot"] / "pages" / "0000.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        parse_account_memory(tmp_path, ACCOUNT_ID)


def test_duplicate_native_id_does_not_create_complete_snapshot(tmp_path):
    result = asyncio.run(capture_account_memory(_Client([_response([_node("same", "a"), _node("same", "b")])]), tmp_path))
    assert not result["complete"]
    assert parse_account_memory(tmp_path, ACCOUNT_ID).memories == []


def test_non_account_category_does_not_become_saved_memory(tmp_path):
    response = _response([_node("native-1", "v1")])
    response["data"]["viewer"]["knowledgeContext"]["scopeByKind"]["memoryCategories"][0]["id"] = "project:memories"
    result = asyncio.run(capture_account_memory(_Client([response]), tmp_path))
    assert not result["complete"]
    assert parse_account_memory(tmp_path, ACCOUNT_ID).memories == []


def test_api_client_requests_observed_read_only_query():
    client = PerplexityAPIClient(None, None)
    captured = {}

    async def fake_fetch(path, method="GET", body=None):
        captured.update({"path": path, "method": method, "body": body})
        return _response([])

    client._fetch = fake_fetch
    asyncio.run(client.list_account_memory_page(after="next-cursor"))
    assert captured["path"].endswith("/rest/perplexity_ask/graphql")
    assert captured["method"] == "POST"
    assert captured["body"]["variables"]["memoriesAfter"] == "next-cursor"
    assert captured["body"]["variables"]["includeKnowledgePage"] is False
    assert captured["body"]["extensions"]["persistedQuery"]["sha256Hash"] == MEMORY_QUERY_HASH
