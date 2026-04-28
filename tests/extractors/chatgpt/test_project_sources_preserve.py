"""Testes da preservation no download_project_sources.

Sem isso, files removidas no servidor sumiriam silenciosamente do indice
local — historico perdido (mesmo binario ainda em disco). Mesma filosofia
do reconciler de conversations: nada se perde se ja foi capturado.
"""

import json
from pathlib import Path

from src.extractors.chatgpt.project_sources import (
    _find_orphan_local_projects,
    _mark_project_as_deleted,
    _merge_with_preserved,
)


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


# ============================================================
# _find_orphan_local_projects + _mark_project_as_deleted
# (project inteiro deletado no servidor)
# ============================================================

def _make_project_dir(root: Path, pid: str, files: list[dict]) -> Path:
    pdir = root / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "_files.json").write_text(json.dumps(files), encoding="utf-8")
    return pdir


def test_find_orphan_local_projects_detects_deleted(tmp_path):
    """g-p-* local que nao esta na lista atual de discovery = orfao."""
    _make_project_dir(tmp_path, "g-p-aaa", [{"file_id": "f1", "name": "x"}])
    _make_project_dir(tmp_path, "g-p-bbb", [{"file_id": "f2", "name": "y"}])
    _make_project_dir(tmp_path, "g-p-ccc", [{"file_id": "f3", "name": "z"}])

    # discovery atual so tem aaa e ccc
    orphans = _find_orphan_local_projects(tmp_path, {"g-p-aaa", "g-p-ccc"})

    assert len(orphans) == 1
    assert orphans[0].name == "g-p-bbb"


def test_find_orphan_returns_empty_when_all_present(tmp_path):
    """Todos os locais estao na discovery atual = nenhum orfao."""
    _make_project_dir(tmp_path, "g-p-aaa", [{"file_id": "f1", "name": "x"}])

    orphans = _find_orphan_local_projects(tmp_path, {"g-p-aaa"})

    assert orphans == []


def test_find_orphan_ignores_non_project_dirs(tmp_path):
    """Pastas que nao comecam com g-p- sao ignoradas (ex: assets/, .git/)."""
    (tmp_path / "assets").mkdir()
    (tmp_path / ".git").mkdir()
    _make_project_dir(tmp_path, "g-p-real", [{"file_id": "f1", "name": "x"}])

    orphans = _find_orphan_local_projects(tmp_path, set())

    assert len(orphans) == 1
    assert orphans[0].name == "g-p-real"


def test_find_orphan_returns_empty_when_root_missing(tmp_path):
    """Root inexistente nao quebra."""
    orphans = _find_orphan_local_projects(tmp_path / "nonexistent", set())
    assert orphans == []


def test_mark_project_as_deleted_flags_all_sources(tmp_path):
    """Project deletado: todas as sources ganham _preserved_missing=true."""
    pdir = _make_project_dir(tmp_path, "g-p-x", [
        {"file_id": "a", "name": "a.pdf"},
        {"file_id": "b", "name": "b.pdf"},
    ])

    marked = _mark_project_as_deleted(pdir)

    assert marked == 2
    files = json.loads((pdir / "_files.json").read_text())
    assert all(f.get("_preserved_missing") is True for f in files)
    assert all("_last_seen_in_server" in f for f in files)


def test_mark_project_as_deleted_idempotent(tmp_path):
    """Source ja preserved nao eh re-marcada (mantem _last_seen original)."""
    pdir = _make_project_dir(tmp_path, "g-p-x", [
        {"file_id": "a", "name": "a.pdf",
         "_preserved_missing": True, "_last_seen_in_server": "2026-04-10"},
        {"file_id": "b", "name": "b.pdf"},  # nova ainda nao preserved
    ])

    marked = _mark_project_as_deleted(pdir)

    assert marked == 1  # so b foi marcada agora
    files = json.loads((pdir / "_files.json").read_text())
    a = next(f for f in files if f["file_id"] == "a")
    b = next(f for f in files if f["file_id"] == "b")
    assert a["_last_seen_in_server"] == "2026-04-10"  # nao foi alterada
    assert b["_preserved_missing"] is True


def test_mark_project_as_deleted_no_files_json(tmp_path):
    """Pasta sem _files.json retorna 0 sem quebrar."""
    pdir = tmp_path / "g-p-empty"
    pdir.mkdir()

    marked = _mark_project_as_deleted(pdir)

    assert marked == 0


def test_mark_project_as_deleted_corrupt_json(tmp_path):
    """_files.json corrompido retorna 0 sem quebrar."""
    pdir = tmp_path / "g-p-x"
    pdir.mkdir()
    (pdir / "_files.json").write_text("not valid {{{")

    marked = _mark_project_as_deleted(pdir)

    assert marked == 0
