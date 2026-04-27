"""Testes dos helpers do orchestrator usados pelo sync.

Cobrem dois bugs reais ja vistos:

1. _find_last_capture deve retornar a pasta com run_started_at mais recente,
   NAO a primeira por nome alfabetico nem por mtime do filesystem.
   Bug original em chatgpt-sync.py: helper usava early return na pasta sem
   sufixo de hora (que ja existia da brute force), em vez de buscar a
   recem-criada com sufixo.

2. _get_max_known_discovery deve varrer recursivamente data/raw/, incluindo
   subpastas (ex: _backup-gpt/), pra que mover raws antigos pra subpasta
   nao reseta a baseline do fail-fast.
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.extractors.chatgpt.orchestrator import (
    _find_last_capture,
    _get_max_known_discovery,
)


def _make_capture_dir(parent: Path, name: str, started_at: datetime, total: int = 1000):
    """Cria pasta de captura fake com capture_log.json + chatgpt_raw.json."""
    d = parent / name
    d.mkdir(parents=True)
    (d / "capture_log.json").write_text(json.dumps({
        "run_started_at": started_at.isoformat(),
        "discovery": {"total": total},
    }))
    (d / "chatgpt_raw.json").write_text("{}")
    return d


# ============================================================
# _find_last_capture
# ============================================================

def test_find_last_capture_picks_most_recent_by_started_at(tmp_path):
    """Cenario do bug do sync: pasta sem sufixo (antiga) + pasta com sufixo (nova).
    Deve retornar a com run_started_at mais recente."""
    older = datetime(2026, 4, 27, 15, 32, tzinfo=timezone.utc)
    newer = datetime(2026, 4, 27, 16, 40, tzinfo=timezone.utc)

    _make_capture_dir(tmp_path, "ChatGPT Data 2026-04-27", older)
    expected = _make_capture_dir(tmp_path, "ChatGPT Data 2026-04-27T16-40", newer)

    result = _find_last_capture(tmp_path)
    assert result is not None
    path, ts = result
    assert path == expected, f"Pegou {path.name} em vez de {expected.name}"
    assert ts == newer


def test_find_last_capture_returns_none_when_empty(tmp_path):
    """Pasta vazia (sem capturas) retorna None."""
    assert _find_last_capture(tmp_path) is None


def test_find_last_capture_skips_dirs_without_capture_log(tmp_path):
    """Pasta sem capture_log.json eh ignorada (captura incompleta)."""
    incomplete = tmp_path / "ChatGPT Data 2026-04-27T17-00"
    incomplete.mkdir()
    # so chatgpt_raw, sem capture_log
    (incomplete / "chatgpt_raw.json").write_text("{}")

    older = datetime(2026, 4, 27, 15, 32, tzinfo=timezone.utc)
    expected = _make_capture_dir(tmp_path, "ChatGPT Data 2026-04-27", older)

    result = _find_last_capture(tmp_path)
    assert result is not None
    path, _ = result
    assert path == expected


def test_find_last_capture_ignores_non_chatgpt_dirs(tmp_path):
    """So considera dirs que comecam com 'ChatGPT Data'."""
    # Cria capture valida em pasta com nome irrelevante
    foreign = tmp_path / "Some Other Tool"
    foreign.mkdir()
    (foreign / "capture_log.json").write_text(json.dumps({
        "run_started_at": "2027-01-01T00:00:00+00:00",
        "discovery": {"total": 9999},
    }))
    (foreign / "chatgpt_raw.json").write_text("{}")

    valid_ts = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    expected = _make_capture_dir(tmp_path, "ChatGPT Data 2026-04-27", valid_ts)

    result = _find_last_capture(tmp_path)
    path, _ = result
    assert path == expected


# ============================================================
# _get_max_known_discovery
# ============================================================

def test_get_max_known_discovery_recursive(tmp_path):
    """Varre subpastas (ex: _backup-gpt/) — mover raws antigos pra backup
    nao reseta a baseline."""
    older = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 4, 27, 15, 32, tzinfo=timezone.utc)

    backup = tmp_path / "_backup-gpt"
    backup.mkdir()
    _make_capture_dir(backup, "ChatGPT Data 2026-04-23T12-40", older, total=1175)

    _make_capture_dir(tmp_path, "ChatGPT Data 2026-04-27", newer, total=1164)

    # Esperado: pega max (1175 do backup) — recursivo
    assert _get_max_known_discovery(tmp_path) == 1175


def test_get_max_known_discovery_returns_zero_when_empty(tmp_path):
    """Sem capture_logs, retorna 0 (sem baseline → fail-fast nao dispara)."""
    assert _get_max_known_discovery(tmp_path) == 0


def test_get_max_known_discovery_skips_corrupt_logs(tmp_path):
    """Capture_log corrompido eh ignorado, nao quebra o varredor."""
    bad = tmp_path / "ChatGPT Data 2026-04-25"
    bad.mkdir()
    (bad / "capture_log.json").write_text("not valid json {{{")

    good = _make_capture_dir(
        tmp_path, "ChatGPT Data 2026-04-26",
        datetime(2026, 4, 26, tzinfo=timezone.utc),
        total=500,
    )

    assert _get_max_known_discovery(tmp_path) == 500
