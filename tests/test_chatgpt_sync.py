"""Testes do orquestrador chatgpt-sync.py.

Cobre o helper hardlink_existing_binaries — peca chave do design
"capturar uma vez, nunca rebaixar". Sem isso, cada run nova de sync
rebaixaria centenas de MB de assets ja capturados em runs anteriores.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "chatgpt-sync.py"


@pytest.fixture
def sync_module():
    """Carrega chatgpt-sync.py como modulo (nome com hifen impede import direto)."""
    spec = importlib.util.spec_from_file_location("chatgpt_sync", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["chatgpt_sync"] = module
    spec.loader.exec_module(module)
    return module


def _make_raw_with_binaries(parent: Path, name: str,
                              assets: list[str] = None,
                              sources: list[str] = None) -> Path:
    """Cria pasta raw fake com binarios opcionais."""
    d = parent / name
    d.mkdir(parents=True)
    (d / "chatgpt_raw.json").write_text("{}")
    if assets:
        (d / "assets").mkdir()
        for fname in assets:
            (d / "assets" / fname).write_bytes(b"image-bytes-" + fname.encode())
    if sources:
        (d / "project_sources").mkdir()
        for fname in sources:
            sub = d / "project_sources" / "g-p-fake"
            sub.mkdir(exist_ok=True)
            (sub / fname).write_bytes(b"file-bytes-" + fname.encode())
    return d


def test_hardlink_links_assets_from_previous_raw(tmp_path, sync_module):
    """Assets de raw anterior viram hardlink no raw novo (nao rebaixa)."""
    _make_raw_with_binaries(
        tmp_path, "ChatGPT Data 2026-04-23T12-40",
        assets=["file-abc__img.png", "file-def__img.png"],
    )
    target = tmp_path / "ChatGPT Data 2026-04-27T16-45"
    target.mkdir()
    (target / "chatgpt_raw.json").write_text("{}")

    stats = sync_module.hardlink_existing_binaries(target)

    assert stats["linked_assets"] == 2
    assert (target / "assets" / "file-abc__img.png").exists()
    assert (target / "assets" / "file-def__img.png").exists()
    # Hardlink: arquivo no destino e o mesmo inode da origem
    src_inode = (tmp_path / "ChatGPT Data 2026-04-23T12-40" / "assets" / "file-abc__img.png").stat().st_ino
    dst_inode = (target / "assets" / "file-abc__img.png").stat().st_ino
    assert src_inode == dst_inode, "Devia ser hardlink (mesmo inode), nao copia"


def test_hardlink_recursive_through_backup_dirs(tmp_path, sync_module):
    """Encontra binarios em subpastas (ex: _backup-gpt/)."""
    backup = tmp_path / "_backup-gpt"
    backup.mkdir()
    _make_raw_with_binaries(
        backup, "ChatGPT Data 2026-04-23T12-40",
        assets=["file-old__img.png"],
        sources=["doc.pdf"],
    )
    target = tmp_path / "ChatGPT Data 2026-04-27T16-45"
    target.mkdir()
    (target / "chatgpt_raw.json").write_text("{}")

    stats = sync_module.hardlink_existing_binaries(target)

    assert stats["linked_assets"] == 1
    assert stats["linked_sources"] == 1
    assert (target / "assets" / "file-old__img.png").exists()
    assert (target / "project_sources" / "g-p-fake" / "doc.pdf").exists()


def test_hardlink_preserves_existing_files_in_target(tmp_path, sync_module):
    """Se arquivo ja existe no target, nao sobrescreve nem reconta."""
    _make_raw_with_binaries(
        tmp_path, "ChatGPT Data 2026-04-23T12-40",
        assets=["file-abc__img.png"],
    )
    target = tmp_path / "ChatGPT Data 2026-04-27T16-45"
    target.mkdir()
    (target / "chatgpt_raw.json").write_text("{}")
    # Pre-cria com conteudo diferente
    (target / "assets").mkdir()
    (target / "assets" / "file-abc__img.png").write_bytes(b"DO-NOT-OVERWRITE")

    stats = sync_module.hardlink_existing_binaries(target)

    assert stats["linked_assets"] == 0  # Nao linkou (ja existia)
    # Conteudo preservado
    assert (target / "assets" / "file-abc__img.png").read_bytes() == b"DO-NOT-OVERWRITE"


def test_hardlink_returns_zero_when_no_previous_binaries(tmp_path, sync_module):
    """Sem raws anteriores com binarios, retorna 0 sem crashar."""
    target = tmp_path / "ChatGPT Data 2026-04-27T16-45"
    target.mkdir()
    (target / "chatgpt_raw.json").write_text("{}")

    stats = sync_module.hardlink_existing_binaries(target)

    assert stats["linked_assets"] == 0
    assert stats["linked_sources"] == 0


def test_hardlink_picks_most_recent_source(tmp_path, sync_module):
    """Quando ha varios raws com binarios, pega o MAIS RECENTE como fonte."""
    older = _make_raw_with_binaries(
        tmp_path, "ChatGPT Data 2026-04-20",
        assets=["file-old__img.png"],
    )
    # mtime explicito mais antigo
    os.utime(older, (1700000000, 1700000000))
    for f in older.rglob("*"):
        os.utime(f, (1700000000, 1700000000))

    newer = _make_raw_with_binaries(
        tmp_path, "ChatGPT Data 2026-04-25",
        assets=["file-new__img.png"],
    )
    target = tmp_path / "ChatGPT Data 2026-04-27"
    target.mkdir()
    (target / "chatgpt_raw.json").write_text("{}")

    stats = sync_module.hardlink_existing_binaries(target)

    assert stats["linked_assets"] == 1
    # Pegou do mais recente (newer), nao do older
    assert (target / "assets" / "file-new__img.png").exists()
    assert not (target / "assets" / "file-old__img.png").exists()
