"""Kimi raw memory/context reads keep partial evidence without inventing items."""

import asyncio
import hashlib
import json

from src.platforms.kimi.extractor.api_client import KimiAPIClient
from src.platforms.kimi.extractor.memory_context import capture_memory_context


class _Client:
    def __init__(self, *, fail_memory=False, duplicate_project=False):
        self.fail_memory = fail_memory
        self.duplicate_project = duplicate_project
        self.memory_tokens = []
        self.project_tokens = []

    async def list_memory_page(self, page_size=50, page_token=None):
        self.memory_tokens.append(page_token)
        if self.fail_memory and page_token:
            raise RuntimeError("private upstream content")
        if page_token:
            return {"memories": [{"id": "native-2"}], "nextPageToken": "", "memoryLimit": 50}
        return {"memories": [{"id": "native-1"}], "nextPageToken": "next", "memoryLimit": 50}

    async def get_user_setting(self):
        return {"userSetting": {"memory": {"useSemanticMemory": True}}}

    async def get_dream_status(self):
        return {"dreamVault": {"status": "disabled"}, "featureAvailable": True}

    async def list_projects_page(self, page_size=100, page_token=None):
        self.project_tokens.append(page_token)
        projects = [{"id": "project-1"}]
        if self.duplicate_project:
            projects.append({"id": "project-1"})
        return {"projects": projects, "projectCountUsed": 1}

    async def get_project(self, project_id):
        return {"project": {"id": project_id, "name": "private project"}}


def test_capture_raw_surfaces_with_hashes_and_history(tmp_path):
    client = _Client()
    first = asyncio.run(capture_memory_context(client, tmp_path))
    second = asyncio.run(capture_memory_context(_Client(), tmp_path))
    assert first["snapshot"] != second["snapshot"]
    assert all(surface["complete"] for surface in first["surfaces"].values())
    assert first["surfaces"]["account_memory"]["items"] == 2
    assert first["surfaces"]["project_catalog"]["projects"] == 1
    assert client.memory_tokens == [None, "next"]
    assert client.project_tokens == [None]
    manifest = json.loads((first["snapshot"] / "capture.json").read_text())
    assert len(manifest["files"]) == 6
    for relative, metadata in manifest["files"].items():
        assert hashlib.sha256((first["snapshot"] / relative).read_bytes()).hexdigest() == metadata["sha256"]
    assert "private project" not in json.dumps(manifest)


def test_partial_memory_and_project_failures_still_preserve_other_reads(tmp_path):
    result = asyncio.run(capture_memory_context(
        _Client(fail_memory=True, duplicate_project=True), tmp_path,
    ))
    status = result["surfaces"]
    assert not status["account_memory"]["complete"]
    assert not status["project_catalog"]["complete"]
    assert status["user_setting_read"]["complete"]
    assert status["dream_status"]["complete"]
    assert (result["snapshot"] / "memory/pages/0000.json").exists()
    assert (result["snapshot"] / "projects/pages/0000.json").exists()
    assert "private upstream content" not in (result["snapshot"] / "capture.json").read_text()


def test_observed_empty_memory_page_is_complete_but_has_no_item_shape(tmp_path):
    client = _Client()

    async def empty_page(page_size=50, page_token=None):
        return {"nextPageToken": "", "memoryLimit": 50}

    client.list_memory_page = empty_page
    result = asyncio.run(capture_memory_context(client, tmp_path))
    assert result["surfaces"]["account_memory"] == {"complete": True, "items": 0, "pages": 1}
    page = json.loads((result["snapshot"] / "memory/pages/0000.json").read_text())
    assert page["response"] == {"nextPageToken": "", "memoryLimit": 50}


def test_api_client_uses_observed_read_only_transports():
    client = KimiAPIClient(None, None)
    calls = []

    async def fake_post(path, body=None):
        calls.append((path, body))
        return {}

    client._post = fake_post

    async def run():
        await client.list_memory_page(page_token="cursor")
        await client.get_user_setting()
        await client.get_dream_status()
        await client.list_projects_page(page_token="cursor")
        await client.get_project("project-1")

    asyncio.run(run())
    assert [path.rsplit("/", 1)[-1] for path, _ in calls] == [
        "ListMemories", "GetUserSetting", "GetDreamStatus", "ListProjects", "GetProject",
    ]
    assert calls[0][1] == {"page_size": 50, "page_token": "cursor"}
    assert calls[3][1] == {"page_size": 100, "include_pinned": True, "page_token": "cursor"}
    assert calls[4][1] == {"project_id": "project-1"}
