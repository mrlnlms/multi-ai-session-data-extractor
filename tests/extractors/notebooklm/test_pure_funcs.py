"""Smoke tests pra funções puras do extractor NotebookLM."""

from __future__ import annotations

import json
from pathlib import Path

from src.extractors.notebooklm.fetcher import (
    _extract_source_uuids,
    _extract_mind_map_uuid,
)
from src.extractors.notebooklm.orchestrator import _get_max_known_discovery


class TestExtractSourceUuids:
    def test_empty_returns_empty(self):
        assert _extract_source_uuids([]) == []
        assert _extract_source_uuids(None) == []

    def test_extracts_uuids_from_positional_schema(self):
        """Schema rLM1Ne: data[0] = [title, [sources], uuid, emoji].
        Cada source em [1]: [[uuid], filename, [meta], [flag]]."""
        raw = [
            [
                "Notebook Title",
                [
                    [["src-uuid-1"], "doc1.pdf", [], []],
                    [["src-uuid-2"], "doc2.pdf", [], []],
                    [["src-uuid-3"], "doc3.pdf", [], []],
                ],
                "notebook-uuid",
                "📓",
            ]
        ]
        result = _extract_source_uuids(raw)
        assert result == ["src-uuid-1", "src-uuid-2", "src-uuid-3"]

    def test_skips_malformed_entries(self):
        raw = [
            [
                "Notebook",
                [
                    [["valid-uuid"], "doc.pdf", [], []],
                    "not a list",  # malformado
                    [],  # vazio
                    [["another-uuid"], "doc2.pdf", [], []],
                ],
                "nb-uuid",
            ]
        ]
        result = _extract_source_uuids(raw)
        assert result == ["valid-uuid", "another-uuid"]


class TestExtractMindMapUuid:
    def test_empty_returns_none(self):
        assert _extract_mind_map_uuid(None) is None
        assert _extract_mind_map_uuid([]) is None

    def test_extracts_when_present(self):
        # Schema empírico: hPTbtc retorna [[[uuid]]] (3 níveis)
        raw = [[["mind-map-uuid-abc"]]]
        result = _extract_mind_map_uuid(raw)
        assert result == "mind-map-uuid-abc"


class TestGetMaxKnownDiscovery:
    def test_no_dir_returns_zero(self, tmp_path):
        assert _get_max_known_discovery(tmp_path / "ghost") == 0

    def test_reads_max_notebooks_discovered(self, tmp_path):
        log = tmp_path / "capture_log.jsonl"
        log.write_text("\n".join([
            json.dumps({"totals": {"notebooks_discovered": 40}}),
            json.dumps({"totals": {"notebooks_discovered": 95}}),
            json.dumps({"totals": {"notebooks_discovered": 60}}),
        ]) + "\n", encoding="utf-8")
        assert _get_max_known_discovery(tmp_path) == 95
