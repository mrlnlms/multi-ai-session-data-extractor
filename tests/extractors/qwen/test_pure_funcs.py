"""Smoke tests pra funções puras do extractor Qwen."""

from __future__ import annotations

import json
from pathlib import Path

from src.extractors.qwen.asset_downloader import _target_path
from src.extractors.qwen.orchestrator import _get_max_known_discovery


class TestTargetPath:
    def test_user_upload_uses_filename(self, tmp_path):
        info = {
            "conv_id": "abc123",
            "source_type": "user_upload",
            "file_name": "my-doc.pdf",
        }
        result = _target_path(tmp_path, "https://x.com/foo", info, "application/pdf")
        assert result.parent == tmp_path / "abc123"
        assert result.name == "my-doc.pdf"

    def test_project_file_uses_filename(self, tmp_path):
        info = {
            "conv_id": "abc",
            "source_type": "project_file",
            "file_name": "data.csv",
        }
        result = _target_path(tmp_path, "https://x.com/foo", info, "text/csv")
        assert result.name == "data.csv"

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
