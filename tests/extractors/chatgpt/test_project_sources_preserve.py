"""Testes da preservation no download_project_sources.

Sem isso, files removidas no servidor sumiriam silenciosamente do indice
local — historico perdido (mesmo binario ainda em disco). Mesma filosofia
do reconciler de conversations: nada se perde se ja foi capturado.
"""

import json
from pathlib import Path

from src.extractors.chatgpt.project_sources import _merge_with_preserved


def test_no_existing_index_returns_current_as_is(tmp_path):
    """Sem indice anterior, retorna files atuais sem flag."""
    current = [{"file_id": "a", "name": "a.pdf"}, {"file_id": "b", "name": "b.pdf"}]
    merged, count = _merge_with_preserved(current, tmp_path / "_files.json")
    assert merged == current
    assert count == 0


def test_file_removed_from_server_is_preserved(tmp_path):
    """File ausente no atual (mas presente no anterior) vira _preserved_missing."""
    index = tmp_path / "_files.json"
    index.write_text(json.dumps([
        {"file_id": "a", "name": "a.pdf"},
        {"file_id": "b", "name": "b.pdf"},
    ]))
    current = [{"file_id": "a", "name": "a.pdf"}]  # b sumiu

    merged, count = _merge_with_preserved(current, index)

    assert count == 1
    assert len(merged) == 2
    fids = [f["file_id"] for f in merged]
    assert "a" in fids
    assert "b" in fids
    preserved_b = next(f for f in merged if f["file_id"] == "b")
    assert preserved_b["_preserved_missing"] is True
    assert "_last_seen_in_server" in preserved_b


def test_already_preserved_keeps_original_last_seen(tmp_path):
    """File ja marcada como preserved nao tem _last_seen_in_server resetada."""
    index = tmp_path / "_files.json"
    index.write_text(json.dumps([
        {"file_id": "old", "name": "old.pdf",
         "_preserved_missing": True, "_last_seen_in_server": "2026-04-15"},
    ]))
    current = []  # ainda ausente

    merged, count = _merge_with_preserved(current, index)

    assert count == 1
    assert merged[0]["_last_seen_in_server"] == "2026-04-15"


def test_file_returns_to_server_drops_preserved_flag(tmp_path):
    """File que volta ao servidor: aparece no current sem flag preserved."""
    index = tmp_path / "_files.json"
    index.write_text(json.dumps([
        {"file_id": "a", "name": "a.pdf",
         "_preserved_missing": True, "_last_seen_in_server": "2026-04-15"},
    ]))
    current = [{"file_id": "a", "name": "a.pdf"}]  # voltou

    merged, count = _merge_with_preserved(current, index)

    assert count == 0
    assert len(merged) == 1
    # File volta limpa, sem flags antigas
    assert "_preserved_missing" not in merged[0]


def test_corrupt_index_falls_back_to_current(tmp_path):
    """Indice corrompido nao trava — usa so o current."""
    index = tmp_path / "_files.json"
    index.write_text("not valid json {{{")
    current = [{"file_id": "a", "name": "a.pdf"}]

    merged, count = _merge_with_preserved(current, index)

    assert merged == current
    assert count == 0
