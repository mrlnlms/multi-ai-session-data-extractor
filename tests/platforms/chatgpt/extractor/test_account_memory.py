"""Lossless account exports, historical preservation and independent failures."""

import hashlib
import json
from unittest.mock import AsyncMock

import pytest

from src.platforms.chatgpt.extractor.account_memory import capture_account_memory, _summary_payload
from src.platforms.chatgpt.extractor.models import CaptureReport


def _report():
    return CaptureReport(run_started_at="", run_finished_at="", duration_seconds=0)


def _client(payload=None):
    client = AsyncMock()
    client.fetch_memories.return_value = payload if payload is not None else {
        "memories": [{"id": "m1", "content": "olá", "conversation_id": None,
                      "updated_at": "2026-09-24T00:00:00Z", "unknown": [1, 2]}],
        "unknown_top_level": {"value": True},
    }
    client.fetch_instructions.return_value = {"about_user_message": "researcher", "enabled": True}
    client.fetch_memory_summary_checksum.return_value = {
        "sourceChecksum": "source", "cachedSourceChecksum": "source", "isStale": False,
    }
    client.fetch_memory_summary.return_value = 'event: done\ndata: {"sections": []}\n\ndata: [DONE]\n\n'
    return client


async def test_complete_payload_and_provenance_survive_changed_and_empty_captures(tmp_path):
    client = _client()
    original = client.fetch_memories.return_value
    first_report = _report()
    await capture_account_memory(client, tmp_path, first_report)
    history = tmp_path / "_account_memory" / "saved_memories"
    first = next(history.glob("*/capture.json"))
    metadata = json.loads(first.read_text())
    raw_path = first.parent / "chatgpt_memories.json"
    raw_bytes = raw_path.read_bytes()
    assert json.loads(raw_bytes) == original
    assert metadata["captured_at"].endswith("+00:00")
    assert metadata["request"] == {
        "method": "GET", "path": "/backend-api/memories",
        "params": {"include_memory_entries": "true"},
    }
    assert metadata["files"][raw_path.name]["sha256"] == hashlib.sha256(raw_bytes).hexdigest()
    assert not first_report.errors

    client.fetch_memories.return_value = {"memories": [{"id": "m1", "content": "changed"}]}
    await capture_account_memory(client, tmp_path, _report())
    client.fetch_memories.return_value = {"memories": []}
    await capture_account_memory(client, tmp_path, _report())
    assert len(list(history.glob("*/capture.json"))) == 3
    assert raw_path.read_bytes() == raw_bytes
    assert json.loads((tmp_path / "chatgpt_memories.json").read_text()) == {"memories": []}
    assert "olá" not in (tmp_path / "chatgpt_memories.md").read_text()
    assert len(list((tmp_path / "_account_memory" / "instructions").glob("*/capture.json"))) == 3


async def test_previous_exports_preserved_byte_for_byte_without_invented_dates(tmp_path):
    previous = {
        "chatgpt_memories.md": b"# Legacy\r\n- older fact\r\n",
        "chatgpt_memories.json": b'{"memories":[{"content":"old"}]}',
        "chatgpt_instructions.json": b'{"about_user_message": "old"}',
    }
    for name, content in previous.items():
        (tmp_path / name).write_bytes(content)
    await capture_account_memory(_client(), tmp_path, _report())
    for name, content in previous.items():
        preserved = tmp_path / "_account_memory" / "prior_exports" / name / hashlib.sha256(content).hexdigest()
        assert preserved.read_bytes() == content


@pytest.mark.parametrize("payload", [{}, {"memories": None}, {"memories": {}},
                                     {"memories": [None]}, {"memories": [{"content": 4}]}, []])
async def test_invalid_memory_response_does_not_replace_exports(tmp_path, payload):
    (tmp_path / "chatgpt_memories.md").write_text("previous")
    report = _report()
    await capture_account_memory(_client(payload), tmp_path, report)
    assert (tmp_path / "chatgpt_memories.md").read_text() == "previous"
    assert not (tmp_path / "chatgpt_memories.json").exists()
    assert (tmp_path / "chatgpt_instructions.json").exists()
    assert report.errors == [{"stage": "account_saved_memories", "error_type": "ValueError"}]


async def test_fetch_failure_is_isolated_and_does_not_log_personal_text(tmp_path, caplog):
    client = _client()
    client.fetch_instructions.side_effect = RuntimeError("private response body")
    (tmp_path / "chatgpt_instructions.json").write_text('{"previous": true}')
    report = _report()
    await capture_account_memory(client, tmp_path, report)
    assert (tmp_path / "chatgpt_memories.json").exists()
    assert json.loads((tmp_path / "chatgpt_instructions.json").read_text()) == {"previous": True}
    assert report.errors == [{"stage": "account_instructions", "error_type": "RuntimeError"}]
    assert "private response body" not in caplog.text
    assert "private response body" not in json.dumps(report.errors)


async def test_snapshot_write_failure_keeps_latest_export(tmp_path, monkeypatch):
    from src.platforms.chatgpt.extractor import account_memory

    real_write = account_memory._atomic_write

    def fail_metadata(path, content):
        if path.name == "capture.json":
            raise OSError("disk full")
        real_write(path, content)

    monkeypatch.setattr(account_memory, "_atomic_write", fail_metadata)
    (tmp_path / "chatgpt_memories.md").write_text("previous")
    report = _report()
    await capture_account_memory(_client(), tmp_path, report)
    assert (tmp_path / "chatgpt_memories.md").read_text() == "previous"
    assert not list((tmp_path / "_account_memory").glob("*/*/capture.json"))
    assert len(report.errors) == 4


async def test_account_isolation_and_legacy_response_key(tmp_path):
    first = tmp_path / "account-first"
    second = tmp_path / "account-second"
    await capture_account_memory(_client(), first, _report())
    await capture_account_memory(_client({"memory_entries": [{"content": "second"}]}), second, _report())
    assert "olá" in (first / "chatgpt_memories.md").read_text()
    assert "second" in (second / "chatgpt_memories.md").read_text()
    assert "olá" not in (second / "chatgpt_memories.md").read_text()


async def test_interrupted_export_refresh_retains_both_old_and_new_evidence(tmp_path, monkeypatch):
    from src.platforms.chatgpt.extractor import account_memory

    real_write = account_memory._atomic_write
    current = tmp_path / "chatgpt_memories.md"
    current.write_bytes(b"previous")

    def fail_markdown_refresh(path, content):
        if path == current:
            raise OSError("disk full")
        real_write(path, content)

    monkeypatch.setattr(account_memory, "_atomic_write", fail_markdown_refresh)
    client = _client()
    report = _report()
    await capture_account_memory(client, tmp_path, report)
    assert current.read_bytes() == b"previous"
    history = tmp_path / "_account_memory"
    preserved = next((history / "prior_exports" / current.name).iterdir())
    assert preserved.read_bytes() == b"previous"
    snapshot = next((history / "saved_memories").glob("*/chatgpt_memories.json"))
    assert json.loads(snapshot.read_text()) == client.fetch_memories.return_value
    assert report.errors == [{"stage": "account_saved_memories", "error_type": "OSError"}]
    assert (tmp_path / "chatgpt_instructions.json").exists()


async def test_summary_keeps_native_followups_and_original_stream(tmp_path):
    payload = {"generatedAtIso": "2026-09-24T00:00:00Z", "sourceChecksum": "source",
               "sections": [{"id": "one", "title": "Title", "description": "text",
                             "followUps": [{"preview": "preview", "prompt": "prompt", "action": "action"}]}],
               "unknown": {"preserved": True}}
    stream = ': comment\r\nevent: started\r\ndata: {}\r\n\r\nevent: future_event\r\ndata: {}\r\n\r\n'
    stream += "event: done\r\n" + "\r\n".join(
        "data: " + line for line in json.dumps(payload, indent=2).splitlines()
    ) + "\r\n\r\ndata: [DONE]\r\n\r\n"
    client = _client()
    client.fetch_memory_summary.return_value = stream
    report = _report()
    await capture_account_memory(client, tmp_path, report)
    assert not report.errors
    assert (tmp_path / "chatgpt_memory_summary.sse").read_bytes() == stream.encode()
    assert json.loads((tmp_path / "chatgpt_memory_summary.json").read_text()) == payload
    metadata_path = next((tmp_path / "_account_memory" / "summary").glob("*/capture.json"))
    metadata = json.loads(metadata_path.read_text())
    assert metadata["complete"] is True
    assert metadata["request"] == {
        "method": "POST", "path": "/backend-api/memories/about_you/summary/stream", "json": {},
    }


@pytest.mark.parametrize("stream", [
    'event: section\ndata: {"section": {}}\n\n',
    'event: done\ndata: {"sections": []}',
    'event: error\ndata: {"message": "private"}\n\n',
    'event: done\ndata: {}\n\n',
    'event: done\ndata: {"sections": [null]}\n\n',
    'event: done\ndata: {"sections": []}\n\nevent: done\ndata: {"sections": []}\n\n',
])
async def test_incomplete_summary_preserved_without_replacing_last_complete(tmp_path, stream, caplog):
    client = _client()
    client.fetch_memory_summary.return_value = stream
    (tmp_path / "chatgpt_memory_summary.json").write_text('{"previous":true}')
    (tmp_path / "chatgpt_memory_summary.sse").write_text("previous stream")
    report = _report()
    await capture_account_memory(client, tmp_path, report)
    assert json.loads((tmp_path / "chatgpt_memory_summary.json").read_text()) == {"previous": True}
    assert (tmp_path / "chatgpt_memory_summary.sse").read_text() == "previous stream"
    metadata_path = next((tmp_path / "_account_memory" / "summary").glob("*/capture.json"))
    assert json.loads(metadata_path.read_text())["complete"] is False
    assert (metadata_path.parent / "chatgpt_memory_summary.sse").read_bytes() == stream.encode()
    assert report.errors == [{"stage": "account_summary", "error_type": "ValueError"}]
    assert "private" not in caplog.text


@pytest.mark.parametrize("count", [0, 3, 8])
def test_summary_has_no_fixed_section_count(count):
    payload = {"sections": [{"id": str(i)} for i in range(count)], "emptyStateMessage": "empty"}
    assert _summary_payload("event: done\ndata: " + json.dumps(payload) + "\n\n") == payload


async def test_checksum_failure_does_not_discard_successful_summary(tmp_path):
    client = _client()
    client.fetch_memory_summary_checksum.side_effect = RuntimeError("unavailable")
    report = _report()
    await capture_account_memory(client, tmp_path, report)
    assert (tmp_path / "chatgpt_memory_summary.json").exists()
    assert report.errors == [{"stage": "account_summary_checksum", "error_type": "RuntimeError"}]
