"""Project settings are native raw context; only instructions become documents."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.platforms.chatgpt.extractor.api_client import ChatGPTAPIClient
from src.platforms.chatgpt.extractor.project_settings import capture_project_settings
from src.platforms.chatgpt.project_settings_parser import parse_project_instructions

ACCOUNT = "11111111-1111-4111-8111-111111111111"
PROJECT = "g-p-first"


def _detail(instructions="Be concise", *, scope="global", enabled=True, project_id=PROJECT):
    return {"gizmo": {"id": project_id, "instructions": instructions,
                      "memory_scope": scope, "memory_enabled": enabled,
                      "unknown": {"retained": True}}, "files": [{"file_id": "file-1"}]}


class _Client:
    def __init__(self, details, *, listed=(PROJECT,), discovery_fails=False):
        self.details = details
        self.listed = listed
        self.discovery_fails = discovery_fails

    async def list_projects(self):
        if self.discovery_fails:
            raise RuntimeError("partial discovery")
        return [SimpleNamespace(id=project_id) for project_id in self.listed]

    async def fetch_project_detail(self, project_id):
        result = self.details[project_id]
        if isinstance(result, Exception):
            raise result
        return result


def _capture(root, detail, **kwargs):
    return asyncio.run(capture_project_settings(_Client({PROJECT: detail}, **kwargs), root))


@pytest.mark.asyncio
async def test_api_detail_keeps_complete_response_and_file_adapter(mocker):
    client = ChatGPTAPIClient(object())
    request = mocker.patch.object(client, "_request_with_retry", new_callable=mocker.AsyncMock,
                                return_value=_detail())
    assert await client.fetch_project_detail(PROJECT) == _detail()
    assert await client.fetch_project_files(PROJECT) == [{"file_id": "file-1"}]
    assert request.await_count == 2


def test_complete_detail_retains_unknown_fields_and_projects_without_chats(tmp_path):
    report = _capture(tmp_path, _detail())
    assert report["projects_captured"] == 1
    [snapshot] = (tmp_path / "_project_settings" / PROJECT).iterdir()
    metadata = json.loads((snapshot / "capture.json").read_text())
    assert metadata["request"] == {"method": "GET", "path": f"/backend-api/gizmos/{PROJECT}"}
    assert metadata["complete"] is True
    assert metadata["settings_complete"] is True
    assert json.loads((snapshot / "project_detail.json").read_text()) == _detail()
    [memory] = parse_project_instructions(tmp_path, ACCOUNT).memories
    assert memory.kind == "project_instructions"
    assert memory.project_key == PROJECT and memory.content == "Be concise"
    assert "memory_scope" not in memory.content
    assert not memory.is_preserved_missing


def test_changed_and_removed_instructions_keep_versions_and_no_project_memory(tmp_path):
    _capture(tmp_path, _detail("First"))
    _capture(tmp_path, _detail("Second", scope="project_only"))
    _capture(tmp_path, _detail("", scope="project_only"))
    result = parse_project_instructions(tmp_path, ACCOUNT)
    assert len(result.memories) == 1 and len(result.versions) == 2
    assert result.memories[0].content == "Second"
    assert result.memories[0].is_preserved_missing
    assert all(version.content in {"First", "Second"} for version in result.versions)
    assert all(evidence.evidence_type == "capture_observed" for evidence in result.temporal_evidence)
    assert all((tmp_path / evidence.locator.split("#")[0]).is_file()
               for evidence in result.temporal_evidence)


def test_empty_initial_instructions_keep_raw_without_canonical_memory(tmp_path):
    _capture(tmp_path, _detail(""))
    assert parse_project_instructions(tmp_path, ACCOUNT).memories == []
    assert len(list((tmp_path / "_project_settings" / PROJECT).glob("*/capture.json"))) == 1


def test_unknown_settings_shape_is_preserved_without_false_removal(tmp_path):
    _capture(tmp_path, _detail())
    report = _capture(tmp_path, {"gizmo": {"id": PROJECT, "new_format": True}})
    assert report["projects_captured"] == 1
    assert len(list((tmp_path / "_project_settings" / PROJECT).glob("*/capture.json"))) == 2
    [memory] = parse_project_instructions(tmp_path, ACCOUNT).memories
    assert memory.content == "Be concise" and not memory.is_preserved_missing


def test_failed_detail_does_not_erase_prior_snapshot_or_infer_missing(tmp_path):
    _capture(tmp_path, _detail())
    report = _capture(tmp_path, RuntimeError("forbidden"), discovery_fails=True)
    assert not report["discovery_succeeded"] and report["projects_captured"] == 0
    assert len(report["errors"]) == 2
    assert len(list((tmp_path / "_project_settings" / PROJECT).glob("*/capture.json"))) == 1
    assert not parse_project_instructions(tmp_path, ACCOUNT).memories[0].is_preserved_missing


def test_wrong_project_identity_is_not_saved(tmp_path):
    report = _capture(tmp_path, _detail(project_id="g-p-other"))
    assert report["projects_captured"] == 0
    assert not (tmp_path / "_project_settings").exists()


def test_corrupt_complete_history_stops_projection(tmp_path):
    _capture(tmp_path, _detail())
    [snapshot] = (tmp_path / "_project_settings" / PROJECT).iterdir()
    (snapshot / "project_detail.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        parse_project_instructions(tmp_path, ACCOUNT)


def test_account_ids_do_not_collide(tmp_path):
    _capture(tmp_path, _detail())
    first = parse_project_instructions(tmp_path, ACCOUNT)
    second = parse_project_instructions(tmp_path, "22222222-2222-4222-8222-222222222222")
    assert first.memories[0].memory_id != second.memories[0].memory_id
