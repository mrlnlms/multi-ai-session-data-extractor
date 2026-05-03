"""Tests pro reconciler NotebookLM (Chunk 13 — review cruzado fix).

Cobertura focada nas funcoes criticas: build_plan, _eq_lenient,
_strip_timestamps, version_bumped behavior, drop_threshold.
"""

import json
from pathlib import Path

import pytest

from src.reconcilers.notebooklm import (
    FEATURES_VERSION, FEATURE_FLAGS,
    NotebookPlan, _eq_lenient, _strip_timestamps,
    build_plan, run_reconciliation,
)


def test_features_version_includes_tr032e():
    """tr032e_source_guide deve estar listado em FEATURE_FLAGS."""
    assert "tr032e_source_guide" in FEATURE_FLAGS
    # FEATURES_VERSION incrementado pra 3 quando tr032e foi adicionado
    assert FEATURES_VERSION >= 3


def test_eq_lenient_timestamps_treated_equal():
    """Timestamps [secs, nanos] em ranges epoch sao tratados como iguais."""
    a = [1777733722, 965000000]
    b = [1777735000, 100000000]
    assert _eq_lenient(a, b) is True


def test_eq_lenient_both_none_equal():
    """Ambos None: equivalentes."""
    assert _eq_lenient(None, None) is True


def test_eq_lenient_none_vs_populated_differs():
    """None vs populado: diferente — força refetch (regressão fix 2026-05-03).

    Bug histórico: retornava True pra QUALQUER lado None, fazendo notebook
    que ganhou chat/guide/mind_map novo virar to_copy ao invés de to_use.
    """
    assert _eq_lenient(None, "x") is False
    assert _eq_lenient([], None) is False
    assert _eq_lenient(None, [["chat turn"]]) is False
    # Caso real: notebook com chat=None que ganhou turns
    prev = {"metadata": [["x"]], "chat": None}
    curr = {"metadata": [["x"]], "chat": [["new turn"]]}
    assert _eq_lenient(prev, curr) is False


def test_eq_lenient_real_diff_detected():
    """Conteudo realmente diferente retorna False."""
    a = ["title 1", "content"]
    b = ["title 2", "content"]
    assert _eq_lenient(a, b) is False


def test_eq_lenient_recursive_dicts():
    a = {"k1": [1777733000, 0], "k2": "value"}
    b = {"k1": [1777740000, 999], "k2": "value"}
    assert _eq_lenient(a, b) is True  # ts diferentes mas equivalentes


def test_strip_timestamps_replaces_pairs():
    """[epoch, nanos] vira '_ts' apos walk recursivo."""
    x = [1, [1777733000, 100], "text", {"ts": [1777740000, 0]}]
    out = _strip_timestamps(x)
    assert out[1] == "_ts"
    assert out[3]["ts"] == "_ts"
    assert out[2] == "text"


def test_strip_timestamps_keeps_non_ts_pairs():
    """Lista de 2 ints fora do range epoch nao vira _ts."""
    x = [42, 99]  # Nao epoch range
    out = _strip_timestamps(x)
    assert out == [42, 99]


def test_build_plan_first_run_no_previous(tmp_path):
    """Primeiro run: tudo novo vira to_use."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "notebooks").mkdir()
    (raw / "notebooks" / "nb1.json").write_text("{}", encoding="utf-8")
    (raw / "discovery_ids.json").write_text(
        json.dumps([{"uuid": "nb1", "title": "Test"}]),
        encoding="utf-8",
    )
    plan = build_plan(raw, previous_merged=None)
    assert "nb1" in plan.to_use
    assert plan.to_copy == []
    assert plan.preserved_missing == []


def test_build_plan_preserved_missing(tmp_path):
    """Notebook sumiu do servidor: vira preserved_missing."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "discovery_ids.json").write_text(
        json.dumps([{"uuid": "nb_active", "title": "Active"}]),
        encoding="utf-8",
    )

    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "discovery_ids.json").write_text(
        json.dumps([
            {"uuid": "nb_active", "title": "Active"},
            {"uuid": "nb_deleted", "title": "Deleted on server"},
        ]),
        encoding="utf-8",
    )
    plan = build_plan(raw, previous_merged=merged)
    assert "nb_deleted" in plan.preserved_missing


def test_build_plan_full_forces_to_use(tmp_path):
    """full=True ignora unchanged check, tudo vira to_use."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "notebooks").mkdir()
    (raw / "notebooks" / "nb1.json").write_text(json.dumps({"uuid": "nb1"}), encoding="utf-8")
    (raw / "discovery_ids.json").write_text(
        json.dumps([{"uuid": "nb1", "title": "Test"}]),
        encoding="utf-8",
    )

    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "notebooks").mkdir()
    (merged / "notebooks" / "nb1.json").write_text(json.dumps({"uuid": "nb1"}), encoding="utf-8")
    (merged / "discovery_ids.json").write_text(
        json.dumps([{"uuid": "nb1", "title": "Test"}]),
        encoding="utf-8",
    )

    plan = build_plan(raw, previous_merged=merged, full=True)
    assert "nb1" in plan.to_use


def test_run_reconciliation_drop_threshold_aborts(tmp_path):
    """Se discovery cair > 50%, reconcile aborta."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "discovery_ids.json").write_text(
        json.dumps([{"uuid": "nb1", "title": "Solo"}]),  # 1 conv
        encoding="utf-8",
    )

    merged = tmp_path / "merged"
    merged.mkdir()
    # Previous tinha 10 convs — atual so 1 = drop > 50%
    prev_disc = [{"uuid": f"nb{i}", "title": f"T{i}"} for i in range(10)]
    (merged / "discovery_ids.json").write_text(json.dumps(prev_disc), encoding="utf-8")

    report = run_reconciliation(raw, merged)
    assert report.aborted is True
    assert "Queda drastica" in report.abort_reason
