"""Testes dos helpers do orchestrator.

Pasta unica cumulativa (refactor 2026-04-27):
- _find_last_capture aceita o dir da pasta unica (ChatGPT/) e retorna
  (path, run_started_at_da_ultima_run) se valida, ou None.
  Suporta capture_log.jsonl (formato novo) e capture_log.json (compat).
- _get_max_known_discovery varre rglob, aceitando jsonl (todas linhas) e
  json (snapshot). Recursivo de proposito — subpastas como _backup-* contam.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.chatgpt.models import ConversationMeta
from src.extractors.chatgpt.orchestrator import (
    _filter_incremental_targets,
    _find_last_capture,
    _get_max_known_discovery,
)


def _make_capture_dir_jsonl(parent: Path, name: str, started_at: datetime, total: int = 1000):
    """Pasta com capture_log.jsonl (formato novo) + chatgpt_raw.json."""
    d = parent / name
    d.mkdir(parents=True)
    entry = {
        "run_started_at": started_at.isoformat(),
        "discovery": {"total": total},
    }
    (d / "capture_log.jsonl").write_text(json.dumps(entry) + "\n")
    (d / "chatgpt_raw.json").write_text("{}")
    return d


def _make_capture_dir_legacy(parent: Path, name: str, started_at: datetime, total: int = 1000):
    """Pasta com capture_log.json (formato antigo, backward compat)."""
    d = parent / name
    d.mkdir(parents=True)
    (d / "capture_log.json").write_text(json.dumps({
        "run_started_at": started_at.isoformat(),
        "discovery": {"total": total},
    }))
    (d / "chatgpt_raw.json").write_text("{}")
    return d


# ============================================================
# _find_last_capture (pasta unica)
# ============================================================

def test_find_last_capture_returns_dir_when_jsonl_exists(tmp_path):
    """Pasta com capture_log.jsonl + chatgpt_raw.json -> retorna (path, ts)."""
    started = datetime(2026, 4, 27, 18, 16, tzinfo=timezone.utc)
    raw_dir = _make_capture_dir_jsonl(tmp_path, "ChatGPT", started)

    result = _find_last_capture(raw_dir)
    assert result is not None
    path, ts = result
    assert path == raw_dir
    assert ts == started


def test_find_last_capture_picks_last_line_in_jsonl(tmp_path):
    """capture_log.jsonl com varias runs -> ts da ultima linha."""
    raw_dir = tmp_path / "ChatGPT"
    raw_dir.mkdir()
    (raw_dir / "chatgpt_raw.json").write_text("{}")
    older = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 4, 27, 18, 16, tzinfo=timezone.utc)
    log = raw_dir / "capture_log.jsonl"
    with open(log, "w") as f:
        f.write(json.dumps({"run_started_at": older.isoformat(), "discovery": {"total": 1000}}) + "\n")
        f.write(json.dumps({"run_started_at": newer.isoformat(), "discovery": {"total": 1168}}) + "\n")

    _, ts = _find_last_capture(raw_dir)
    assert ts == newer


def test_find_last_capture_falls_back_to_legacy_json(tmp_path):
    """Se nao ha capture_log.jsonl mas ha capture_log.json, usa o legacy."""
    started = datetime(2026, 4, 27, 18, 0, tzinfo=timezone.utc)
    raw_dir = _make_capture_dir_legacy(tmp_path, "ChatGPT", started)

    result = _find_last_capture(raw_dir)
    assert result is not None
    _, ts = result
    assert ts == started


def test_find_last_capture_returns_none_when_no_raw(tmp_path):
    """Pasta sem chatgpt_raw.json -> None (captura incompleta)."""
    raw_dir = tmp_path / "ChatGPT"
    raw_dir.mkdir()
    (raw_dir / "capture_log.jsonl").write_text(
        json.dumps({"run_started_at": "2026-04-27T00:00:00+00:00"}) + "\n"
    )
    assert _find_last_capture(raw_dir) is None


def test_find_last_capture_returns_none_when_dir_missing(tmp_path):
    """Pasta inexistente -> None."""
    assert _find_last_capture(tmp_path / "ChatGPT") is None


def test_find_last_capture_returns_none_when_no_log(tmp_path):
    """Pasta com chatgpt_raw mas sem nenhum log -> None."""
    raw_dir = tmp_path / "ChatGPT"
    raw_dir.mkdir()
    (raw_dir / "chatgpt_raw.json").write_text("{}")
    assert _find_last_capture(raw_dir) is None


# ============================================================
# _get_max_known_discovery
# ============================================================

def test_get_max_known_discovery_jsonl(tmp_path):
    """Le todas as linhas do jsonl, pega o maior discovery.total."""
    raw_dir = _make_capture_dir_jsonl(tmp_path, "ChatGPT", datetime.now(timezone.utc), total=100)
    log = raw_dir / "capture_log.jsonl"
    with open(log, "a") as f:
        f.write(json.dumps({"discovery": {"total": 1175}}) + "\n")
        f.write(json.dumps({"discovery": {"total": 800}}) + "\n")

    assert _get_max_known_discovery(tmp_path) == 1175


def test_get_max_known_discovery_recursive(tmp_path):
    """Varre subpastas (ex: _backup-gpt/) — mover raws antigos pra backup
    nao reseta a baseline."""
    older = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 4, 27, 15, 32, tzinfo=timezone.utc)

    backup = tmp_path / "_backup-gpt"
    backup.mkdir()
    _make_capture_dir_legacy(backup, "ChatGPT Data 2026-04-23T12-40", older, total=1175)

    _make_capture_dir_jsonl(tmp_path, "ChatGPT", newer, total=1164)

    assert _get_max_known_discovery(tmp_path) == 1175


def test_get_max_known_discovery_returns_zero_when_empty(tmp_path):
    """Sem capture_logs, retorna 0 (sem baseline → fail-fast nao dispara)."""
    assert _get_max_known_discovery(tmp_path) == 0


def test_get_max_known_discovery_skips_corrupt_logs(tmp_path):
    """Capture_log corrompido eh ignorado, nao quebra o varredor."""
    bad = tmp_path / "ChatGPT Data 2026-04-25"
    bad.mkdir()
    (bad / "capture_log.json").write_text("not valid json {{{")

    _make_capture_dir_legacy(
        tmp_path, "ChatGPT Data 2026-04-26",
        datetime(2026, 4, 26, tzinfo=timezone.utc),
        total=500,
    )

    assert _get_max_known_discovery(tmp_path) == 500


# ============================================================
# _filter_incremental_targets — incremental fetch decision
# ============================================================

def _meta(cid: str, title: str | None, update_time: float):
    return ConversationMeta(
        id=cid, title=title, create_time=1.0, update_time=update_time,
        project_id=None, archived=False,
    )


def test_filter_incremental_includes_new_convs(tmp_path):
    """Conv que nao esta no prev_raw deve ser fetchada."""
    cutoff = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    metas = [_meta("new", "Novo Chat", 1234567890.0)]
    prev_raw = {}  # vazio

    targets = _filter_incremental_targets(metas, prev_raw, cutoff)

    assert targets == ["new"]


def test_filter_incremental_includes_updated_convs(tmp_path):
    """Conv com update_time > cutoff deve ser refetchada."""
    cutoff = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    cutoff_epoch = cutoff.timestamp()
    metas = [_meta("a", "Antigo", cutoff_epoch + 100)]
    prev_raw = {"a": {"id": "a", "title": "Antigo", "update_time": cutoff_epoch - 100}}

    targets = _filter_incremental_targets(metas, prev_raw, cutoff)

    assert targets == ["a"]


def test_filter_incremental_skips_unchanged(tmp_path):
    """Conv com update_time <= cutoff e mesmo title NAO refetchada (incremental skip)."""
    cutoff = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    cutoff_epoch = cutoff.timestamp()
    metas = [_meta("a", "Mesmo Title", cutoff_epoch - 100)]
    prev_raw = {"a": {"id": "a", "title": "Mesmo Title", "update_time": cutoff_epoch - 100}}

    targets = _filter_incremental_targets(metas, prev_raw, cutoff)

    assert targets == []


def test_filter_incremental_detects_rename_without_update_time_change(tmp_path):
    """Guardrail: title mudou (rename) mas update_time igual → forca refetch."""
    cutoff = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    cutoff_epoch = cutoff.timestamp()
    metas = [_meta("a", "Title NOVO", cutoff_epoch - 100)]
    # prev_raw tem title antigo
    prev_raw = {"a": {"id": "a", "title": "Title Antigo", "update_time": cutoff_epoch - 100}}

    targets = _filter_incremental_targets(metas, prev_raw, cutoff)

    assert targets == ["a"], "Rename sem update_time bump deve forcar refetch"


def test_filter_incremental_handles_missing_title_in_meta(tmp_path):
    """Meta com title=None nao quebra a comparacao."""
    cutoff = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    cutoff_epoch = cutoff.timestamp()
    metas = [_meta("a", None, cutoff_epoch - 100)]
    prev_raw = {"a": {"id": "a", "title": "Algum Title", "update_time": cutoff_epoch - 100}}

    targets = _filter_incremental_targets(metas, prev_raw, cutoff)

    # title=None nao dispara rename detection (poderia ser meta incompleta)
    assert targets == []
