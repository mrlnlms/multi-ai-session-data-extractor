"""Smoke tests pra funções puras do extractor Qwen."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from src.platforms.qwen.extractor.asset_downloader import _target_path, download_assets
from src.platforms.qwen.extractor.orchestrator import _get_max_known_discovery


class TestTargetPath:
    def test_user_upload_keeps_readable_collision_safe_filename(self, tmp_path):
        info = {
            "conv_id": "abc123",
            "source_type": "user_upload",
            "file_name": "my-doc.pdf",
            "file_id": "native-1",
        }
        result = _target_path(tmp_path, "https://x.com/foo", info, "application/pdf")
        assert result.parent == tmp_path / "abc123"
        assert result.name.startswith("my-doc__")
        assert result.suffix == ".pdf"

        other = _target_path(
            tmp_path, "https://x.com/other",
            {**info, "file_id": "native-2"}, "application/pdf",
        )
        rotated = _target_path(
            tmp_path, "https://x.com/rotated", info, "application/pdf",
        )
        assert other != result
        assert rotated == result

    def test_project_file_uses_filename(self, tmp_path):
        info = {
            "conv_id": "abc",
            "source_type": "project_file",
            "file_name": "data.csv",
            "file_id": "project-file-1",
        }
        result = _target_path(tmp_path, "https://x.com/foo", info, "text/csv")
        assert result.name.startswith("data__")
        assert result.suffix == ".csv"

    def test_generated_uses_url_path_when_meaningful(self, tmp_path):
        """Pra deep research/dalle, tenta pegar nome do final do URL."""
        info = {"conv_id": "c1", "source_type": "generated", "file_class": "research"}
        result = _target_path(
            tmp_path,
            "https://x.com/path/Relatorio_Final.pdf",
            info,
            "application/pdf",
        )
        # Deve incluir o file_class + hash + nome
        assert result.parent == tmp_path / "c1"
        assert "research_" in result.name
        assert "Relatorio_Final" in result.name


@pytest.mark.asyncio
async def test_downloader_never_collides_distinct_native_uploads(mocker, tmp_path):
    raw = tmp_path / "raw"
    conversations = raw / "conversations"
    conversations.mkdir(parents=True)
    urls = ["https://example.test/first", "https://example.test/second"]
    envelope = {"data": {"id": "conv", "chat": {"history": {"messages": {
        "message": {"files": [
            {"id": "native-1", "name": "image.png", "url": urls[0]},
            {"id": "native-2", "name": "image.png", "url": urls[1]},
        ]}
    }}}}}
    (conversations / "conv.json").write_text(json.dumps(envelope))

    context = mocker.AsyncMock()
    page = mocker.AsyncMock()
    context.new_page.return_value = page

    async def response_for(url, **_kwargs):
        response = mocker.AsyncMock()
        response.ok = True
        response.headers = {"content-type": "image/png"}
        response.body.return_value = b"first" if url == urls[0] else b"second"
        return response

    context.request.get.side_effect = response_for
    stats = await download_assets(context, raw, concurrency=1)

    manifest = json.loads((raw / "assets_manifest.json").read_text())
    paths = [entry["relpath"] for entry in manifest.values()]
    assert stats == {"downloaded": 2, "skipped": 0, "errors": []}
    assert len(set(paths)) == 2
    assert {(raw / "assets" / path).read_bytes() for path in paths} == {
        b"first", b"second",
    }


@pytest.mark.asyncio
async def test_downloader_migrates_legacy_path_without_overwriting_it(mocker, tmp_path):
    raw = tmp_path / "raw"
    conversations = raw / "conversations"
    legacy = raw / "assets" / "conv" / "image.png"
    conversations.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    url = "https://example.test/file"
    envelope = {"data": {"id": "conv", "chat": {"history": {"messages": {
        "message": {"files": [
            {"id": "native-1", "name": "image.png", "url": url},
        ]}
    }}}}}
    (conversations / "conv.json").write_text(json.dumps(envelope))
    manifest_key = hashlib.sha1(url.encode()).hexdigest()[:16]
    (raw / "assets_manifest.json").write_text(json.dumps({manifest_key: {
        "url": url, "conv_id": "conv", "source_type": "user_upload",
        "file_name": "image.png", "file_id": "native-1",
        "content_type": "image/png", "size": 6, "relpath": "conv/image.png",
    }}))

    context = mocker.AsyncMock()
    context.new_page.return_value = mocker.AsyncMock()
    response = mocker.AsyncMock()
    response.ok = True
    response.headers = {"content-type": "image/png"}
    response.body.return_value = b"recovered"
    context.request.get.return_value = response

    stats = await download_assets(context, raw, concurrency=1)
    entry = json.loads((raw / "assets_manifest.json").read_text())[manifest_key]
    assert stats["downloaded"] == 1
    assert entry["previous_relpaths"] == ["conv/image.png"]
    assert legacy.read_bytes() == b"legacy"
    assert (raw / "assets" / entry["relpath"]).read_bytes() == b"recovered"


class TestGetMaxKnownDiscovery:
    def test_no_dir_returns_zero(self, tmp_path):
        assert _get_max_known_discovery(tmp_path / "ghost") == 0

    def test_reads_max_chats_discovered(self, tmp_path):
        log = tmp_path / "capture_log.jsonl"
        log.write_text("\n".join([
            json.dumps({"totals": {"conversations_discovered": 50}}),
            json.dumps({"totals": {"conversations_discovered": 100}}),
        ]) + "\n", encoding="utf-8")
        assert _get_max_known_discovery(tmp_path) == 100
