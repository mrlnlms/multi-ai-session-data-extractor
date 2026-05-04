"""Smoke tests pra funções puras do extractor Perplexity."""

from __future__ import annotations

import json
from pathlib import Path

from src.extractors.perplexity.artifact_downloader import _ext_from_url_or_type
from src.extractors.perplexity.orchestrator import _get_max_known_discovery


class TestExtFromUrlOrType:
    def test_extension_from_url(self):
        assert _ext_from_url_or_type("https://x.com/foo.png", None) == ".png"
        assert _ext_from_url_or_type("https://x.com/file.PDF", None) == ".pdf"
        assert _ext_from_url_or_type("https://x.com/script.py", None) == ".py"

    def test_extension_strips_query_string(self):
        assert _ext_from_url_or_type("https://x.com/foo.png?token=abc", None) == ".png"

    def test_fallback_to_asset_type(self):
        # URL sem extensão — usa asset_type
        assert _ext_from_url_or_type("https://x.com/no-ext", "GENERATED_IMAGE") == ".png"
        assert _ext_from_url_or_type("https://x.com/no-ext", "CODE_FILE") == ".md"
        assert _ext_from_url_or_type("https://x.com/no-ext", "CHART") == ".png"

    def test_fallback_bin(self):
        assert _ext_from_url_or_type("https://x.com/no-ext", None) == ".bin"
        assert _ext_from_url_or_type("https://x.com/no-ext", "UNKNOWN_TYPE") == ".bin"


class TestGetMaxKnownDiscovery:
    def test_no_dir_returns_zero(self, tmp_path):
        assert _get_max_known_discovery(tmp_path / "ghost") == 0

    def test_reads_max_threads_discovered(self, tmp_path):
        log = tmp_path / "capture_log.jsonl"
        log.write_text("\n".join([
            json.dumps({"totals": {"threads_discovered": 50}}),
            json.dumps({"totals": {"threads_discovered": 80}}),
            json.dumps({"totals": {"threads_discovered": 30}}),
        ]) + "\n", encoding="utf-8")
        assert _get_max_known_discovery(tmp_path) == 80
