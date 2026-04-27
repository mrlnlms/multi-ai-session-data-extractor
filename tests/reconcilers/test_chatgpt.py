"""Testes do reconciler."""

import json
from pathlib import Path

import pytest

from src.reconcilers.models import Plan, ReconcileReport
from src.reconcilers.chatgpt import build_plan
from src.reconcilers.chatgpt import run_reconciliation


def test_plan_dataclass():
    plan = Plan(
        to_use_from_current=["a"],
        to_copy_from_previous=["b"],
        missing_from_server=["c"],
    )
    assert plan.to_use_from_current == ["a"]


def test_reconcile_report_summary():
    r = ReconcileReport(
        added=1, updated=2, copied=3, preserved_missing=4, validation_warnings=[]
    )
    assert "added=1" in r.summary()


def _conv(id_, update_time):
    return {"id": id_, "update_time": update_time, "mapping": {}}


def _raw_dict(convs):
    return {"conversations": {c["id"]: c for c in convs}}


def test_build_plan_no_previous_all_new():
    current_raw = _raw_dict([_conv("a", 10.0), _conv("b", 20.0)])
    plan = build_plan(current_raw, previous_merged=None)
    assert sorted(plan.to_use_from_current) == ["a", "b"]
    assert plan.to_copy_from_previous == []
    assert plan.missing_from_server == []


def test_build_plan_unchanged_goes_to_copy():
    previous = _raw_dict([_conv("a", 10.0)])
    current = _raw_dict([_conv("a", 10.0)])  # mesmo update_time
    plan = build_plan(current, previous)
    assert plan.to_copy_from_previous == ["a"]
    assert plan.to_use_from_current == []


def test_build_plan_updated_goes_to_current():
    previous = _raw_dict([_conv("a", 10.0)])
    current = _raw_dict([_conv("a", 20.0)])  # update_time mais recente
    plan = build_plan(current, previous)
    assert plan.to_use_from_current == ["a"]
    assert plan.to_copy_from_previous == []


def test_build_plan_missing_from_server_preserved():
    previous = _raw_dict([_conv("a", 10.0), _conv("b", 15.0)])
    current = _raw_dict([_conv("a", 10.0)])  # b sumiu
    plan = build_plan(current, previous)
    assert sorted(plan.to_copy_from_previous) == ["a", "b"]  # a unchanged + b missing
    assert plan.missing_from_server == ["b"]


def test_build_plan_enrichment_changed_goes_to_current():
    """Mesmo update_time, mas raw atual tem _project_name que previous nao tem → to_use.

    Enrichment local (_project_name, _project_id, _archived, _last_seen_in_server) e
    injetado pelo orchestrator sem alterar update_time. Sem esse branch, o reconciler
    copiaria do previous perdendo o enrichment novo.
    """
    prev_conv = _conv("a", 10.0)
    curr_conv = _conv("a", 10.0)  # mesmo update_time
    curr_conv["_project_name"] = "Studies"
    curr_conv["_project_id"] = "proj-123"
    previous = _raw_dict([prev_conv])
    current = _raw_dict([curr_conv])
    plan = build_plan(current, previous)
    assert plan.to_use_from_current == ["a"]
    assert plan.to_copy_from_previous == []


def test_build_plan_enrichment_unchanged_goes_to_copy():
    """Mesmo update_time E mesmos campos _* semanticos → to_copy (sem trabalho redundante)."""
    prev_conv = _conv("a", 10.0)
    prev_conv["_project_name"] = "Studies"
    prev_conv["_project_id"] = "proj-123"
    curr_conv = _conv("a", 10.0)
    curr_conv["_project_name"] = "Studies"
    curr_conv["_project_id"] = "proj-123"
    previous = _raw_dict([prev_conv])
    current = _raw_dict([curr_conv])
    plan = build_plan(current, previous)
    assert plan.to_copy_from_previous == ["a"]
    assert plan.to_use_from_current == []


def test_build_plan_only_operational_enrichment_diff_goes_to_copy():
    """_last_seen_in_server eh operacional (muda toda captura). Diff so nele NAO triggera to_use.

    Sem essa blacklist, reconciles subsequentes cairiam sempre em to_use (orchestrator
    injeta _last_seen_in_server=today a cada run), virando full rewrite toda vez e
    perdendo a otimizacao unchanged→copy.
    """
    prev_conv = _conv("a", 10.0)
    prev_conv["_project_name"] = "Studies"
    prev_conv["_last_seen_in_server"] = "2026-04-23"
    curr_conv = _conv("a", 10.0)
    curr_conv["_project_name"] = "Studies"
    curr_conv["_last_seen_in_server"] = "2026-04-24"  # operacional, data diferente
    previous = _raw_dict([prev_conv])
    current = _raw_dict([curr_conv])
    plan = build_plan(current, previous)
    assert plan.to_copy_from_previous == ["a"]
    assert plan.to_use_from_current == []


def test_build_plan_mixed():
    previous = _raw_dict([
        _conv("a", 10.0),  # unchanged
        _conv("b", 15.0),  # missing from server
        _conv("c", 20.0),  # updated
    ])
    current = _raw_dict([
        _conv("a", 10.0),      # unchanged
        _conv("c", 25.0),      # updated (mais recente)
        _conv("d", 30.0),      # novo
    ])
    plan = build_plan(current, previous)
    assert sorted(plan.to_use_from_current) == ["c", "d"]
    assert sorted(plan.to_copy_from_previous) == ["a", "b"]  # a unchanged + b missing
    assert plan.missing_from_server == ["b"]


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_run_reconciliation_first_time_no_previous(tmp_path):
    raw_dir = tmp_path / "raw" / "ChatGPT Data 2026-04-23"
    _write_json(
        raw_dir / "chatgpt_raw.json",
        _raw_dict([_conv("a", 10.0), _conv("b", 20.0)]),
    )
    merged_base = tmp_path / "merged" / "ChatGPT"
    report = run_reconciliation(raw_dir, merged_base)

    assert report.added == 2
    assert report.copied == 0
    assert not report.aborted

    merged_file = next(merged_base.glob("*/chatgpt_merged.json"))
    merged = json.loads(merged_file.read_text())
    assert set(merged["conversations"].keys()) == {"a", "b"}


def test_run_reconciliation_preserves_missing_from_server(tmp_path, mocker):
    """b foi deletada no servidor. Base local preserva."""
    # Patch datetime.now() dentro do modulo run_reconciliation pra data fixa
    mock_dt = mocker.patch("src.reconcilers.chatgpt.datetime")
    mock_dt.now.return_value.strftime.return_value = "2026-04-23"
    mock_dt.now.return_value.isoformat.return_value = "2026-04-23T00:00:00"

    # Setup: merged anterior tem a, b. Raw atual so tem a (b foi deletada no servidor).
    merged_base = tmp_path / "merged" / "ChatGPT"
    prev_dir = merged_base / "2026-04-10"
    _write_json(
        prev_dir / "chatgpt_merged.json",
        {"conversations": {
            "a": {"id": "a", "update_time": 10.0, "mapping": {}, "_last_seen_in_server": "2026-04-10"},
            "b": {"id": "b", "update_time": 15.0, "mapping": {"m1": {}}, "_last_seen_in_server": "2026-04-10"},
        }},
    )

    raw_dir = tmp_path / "raw" / "ChatGPT Data 2026-04-23"
    _write_json(
        raw_dir / "chatgpt_raw.json",
        {"conversations": {
            "a": {"id": "a", "update_time": 10.0, "mapping": {}},
        }},
    )

    report = run_reconciliation(raw_dir, merged_base)

    assert report.preserved_missing == 1
    # Find the NEW merged file (2026-04-23 subdir) - glob returns both old and new, pick new
    merged_files = list(merged_base.glob("*/chatgpt_merged.json"))
    new_merged = next(p for p in merged_files if "2026-04-23" in str(p))
    merged = json.loads(new_merged.read_text())
    assert "b" in merged["conversations"]
    # b preservada, _last_seen_in_server NAO foi atualizado
    assert merged["conversations"]["b"]["_last_seen_in_server"] == "2026-04-10"
    # a presente, _last_seen_in_server atualizado
    assert merged["conversations"]["a"]["_last_seen_in_server"] == "2026-04-23"


def test_run_reconciliation_aborts_on_drastic_drop(tmp_path):
    """Queda <= 50% aborta sem sobrescrever."""
    merged_base = tmp_path / "merged" / "ChatGPT"
    prev_dir = merged_base / "2026-04-10"
    _write_json(
        prev_dir / "chatgpt_merged.json",
        {"conversations": {f"c{i}": {"id": f"c{i}", "update_time": 1.0, "mapping": {}} for i in range(100)}},
    )

    raw_dir = tmp_path / "raw" / "ChatGPT Data 2026-04-23"
    _write_json(
        raw_dir / "chatgpt_raw.json",
        {"conversations": {f"c{i}": {"id": f"c{i}", "update_time": 1.0, "mapping": {}} for i in range(40)}},
    )

    report = run_reconciliation(raw_dir, merged_base)
    assert report.aborted is True
    assert "queda" in report.abort_reason.lower()
    # Nao criou pasta 2026-04-23 em merged_base
    # (pode existir se datetime nao mockado — checar se novo arquivo merged.json NAO foi criado)
    new_merged_files = [p for p in merged_base.glob("*/chatgpt_merged.json") if "2026-04-10" not in str(p)]
    assert len(new_merged_files) == 0
