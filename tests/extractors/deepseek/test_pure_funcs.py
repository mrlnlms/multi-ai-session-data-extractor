"""Smoke tests pra funções puras do extractor DeepSeek."""

from __future__ import annotations

import json
from pathlib import Path

from src.extractors.deepseek.asset_downloader import _collect_files
from src.extractors.deepseek.orchestrator import _get_max_known_discovery


class TestCollectFiles:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert _collect_files(tmp_path) == []

    def test_collects_files_from_messages(self, tmp_path):
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()
        (conv_dir / "c1.json").write_text(json.dumps({
            "chat_session": {"id": "c1"},
            "chat_messages": [
                {
                    "message_id": "m1",
                    "files": [
                        {"id": "f1", "name": "doc.pdf", "size": 1024},
                        {"id": "f2", "name": "img.png", "size": 2048},
                    ],
                },
            ],
        }), encoding="utf-8")

        result = _collect_files(tmp_path)
        ids = {r["file_id"] for r in result}
        assert ids == {"f1", "f2"}
        # Cada entry tem conv_id e message_id
        assert all(r.get("conv_id") == "c1" for r in result)

    def test_skips_files_without_id(self, tmp_path):
        """File sem `id` é ignorado defensivamente."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()
        (conv_dir / "c1.json").write_text(json.dumps({
            "chat_session": {"id": "c1"},
            "chat_messages": [
                {
                    "message_id": "m1",
                    "files": [
                        {"id": "f1", "name": "ok.pdf"},
                        {"name": "no-id.pdf"},  # sem id — deve ser pulado
                    ],
                },
            ],
        }), encoding="utf-8")

        result = _collect_files(tmp_path)
        assert len(result) == 1
        assert result[0]["file_id"] == "f1"


class TestGetMaxKnownDiscovery:
    def test_no_dir_returns_zero(self, tmp_path):
        assert _get_max_known_discovery(tmp_path / "ghost") == 0

    def test_reads_max(self, tmp_path):
        log = tmp_path / "capture_log.jsonl"
        log.write_text("\n".join([
            json.dumps({"totals": {"conversations_discovered": 30}}),
            json.dumps({"totals": {"conversations_discovered": 75}}),
        ]) + "\n", encoding="utf-8")
        assert _get_max_known_discovery(tmp_path) == 75
