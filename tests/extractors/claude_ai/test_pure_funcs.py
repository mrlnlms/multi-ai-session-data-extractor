"""Smoke tests pra funções puras do extractor Claude.ai."""

from __future__ import annotations

import json
from pathlib import Path

from src.extractors.claude_ai.asset_downloader import _scan_file_uuids
from src.extractors.claude_ai.orchestrator import _get_max_known_discovery


def _make_conv(raw_dir: Path, conv_uuid: str, files: list[dict]) -> Path:
    """Cria 1 conversation JSON em raw_dir/conversations/."""
    conv_dir = raw_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv = {
        "uuid": conv_uuid,
        "chat_messages": [{"files": files}] if files else [],
    }
    p = conv_dir / f"{conv_uuid}.json"
    p.write_text(json.dumps(conv), encoding="utf-8")
    return p


class TestScanFileUuids:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert _scan_file_uuids(tmp_path) == []

    def test_extracts_files_from_messages(self, tmp_path):
        _make_conv(tmp_path, "conv1", files=[
            {"file_uuid": "u1", "file_kind": "image", "file_name": "img.png"},
            {"file_uuid": "u2", "file_kind": "document", "file_name": "doc.pdf"},
        ])
        result = _scan_file_uuids(tmp_path)
        uuids = {r[0] for r in result}
        assert uuids == {"u1", "u2"}

    def test_dedup_across_convs(self, tmp_path):
        """Mesmo file_uuid em 2 convs aparece 1 vez só."""
        _make_conv(tmp_path, "conv1", files=[
            {"file_uuid": "shared", "file_kind": "image", "file_name": "x.png"},
        ])
        _make_conv(tmp_path, "conv2", files=[
            {"file_uuid": "shared", "file_kind": "image", "file_name": "x.png"},
        ])
        result = _scan_file_uuids(tmp_path)
        assert len(result) == 1


class TestGetMaxKnownDiscovery:
    def test_no_dir_returns_zero(self, tmp_path):
        assert _get_max_known_discovery(tmp_path / "ghost") == 0

    def test_reads_max(self, tmp_path):
        log = tmp_path / "capture_log.jsonl"
        log.write_text("\n".join([
            json.dumps({"totals": {"conversations_discovered": 50}}),
            json.dumps({"totals": {"conversations_discovered": 200}}),
            json.dumps({"totals": {"conversations_discovered": 100}}),
        ]) + "\n", encoding="utf-8")
        assert _get_max_known_discovery(tmp_path) == 200
