"""Smoke tests pra funções puras do extractor Gemini.

Cobre `extract_image_urls` (puro, recebe dict → lista) e
`_get_max_known_discovery` (lê capture_log.jsonl).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.extractors.gemini.api_client import extract_image_urls
from src.extractors.gemini.orchestrator import _get_max_known_discovery


# === extract_image_urls ===


class TestExtractImageUrls:
    def test_empty_returns_empty(self):
        assert extract_image_urls({}) == []
        assert extract_image_urls([]) == []

    def test_extracts_googleusercontent_urls(self):
        # Estrutura simulada de raw Gemini com URLs de imagem
        raw = {
            "messages": [
                {"text": "https://lh3.googleusercontent.com/some/image-abc123"},
                {"text": "outra https://lh3.googleusercontent.com/other/image-xyz"},
            ]
        }
        urls = extract_image_urls(raw)
        assert len(urls) == 2
        assert all("googleusercontent" in u for u in urls)

    def test_dedup_preserves_order(self):
        raw = {
            "msg1": "https://lh3.googleusercontent.com/abc",
            "msg2": "https://lh3.googleusercontent.com/abc",  # dup
            "msg3": "https://lh3.googleusercontent.com/xyz",
        }
        urls = extract_image_urls(raw)
        assert len(urls) == 2  # dup removida
        assert urls[0].endswith("abc")
        assert urls[1].endswith("xyz")


# === _get_max_known_discovery ===


class TestGetMaxKnownDiscovery:
    def test_no_dir_returns_zero(self, tmp_path):
        nonexistent = tmp_path / "ghost"
        assert _get_max_known_discovery(nonexistent) == 0

    def test_reads_max_from_jsonl(self, tmp_path):
        log = tmp_path / "capture_log.jsonl"
        log.write_text("\n".join([
            json.dumps({"totals": {"conversations_discovered": 50}}),
            json.dumps({"totals": {"conversations_discovered": 80}}),
            json.dumps({"totals": {"conversations_discovered": 30}}),
        ]) + "\n", encoding="utf-8")
        assert _get_max_known_discovery(tmp_path) == 80

    def test_recursive_finds_logs_in_subdirs(self, tmp_path):
        """Logs em subpastas (ex: _backup-*) também contam pra baseline."""
        sub = tmp_path / "_backup-old"
        sub.mkdir()
        (sub / "capture_log.jsonl").write_text(
            json.dumps({"totals": {"conversations_discovered": 100}}) + "\n",
            encoding="utf-8",
        )
        # Log atual menor
        (tmp_path / "capture_log.jsonl").write_text(
            json.dumps({"totals": {"conversations_discovered": 30}}) + "\n",
            encoding="utf-8",
        )
        # Maior é o da subpasta
        assert _get_max_known_discovery(tmp_path) == 100
