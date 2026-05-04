"""Smoke tests pro reconciler DeepSeek.

Cobre os 5 cenários canônicos de qualquer reconciler:
- first_run_all_added: sem previous, tudo vira `added`
- unchanged_goes_to_copy: mesmo updated_at → `copied`
- updated_at_bumped_goes_to_use: updated_at maior → `updated`
- preserved_missing: conv some do current mas estava em prev → preserved
- idempotent: rodar 2x produz mesmos bytes

Fixtures mínimas (sem dados pessoais reais).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reconcilers.deepseek import (
    DeepSeekPlan,
    DeepSeekReconcileReport,
    build_plan,
    run_reconciliation,
)


# === Helpers de fixture ===


def _make_raw_dir(base: Path, convs: list[dict]) -> Path:
    """Cria raw_dir mínimo: discovery_ids.json + conversations/<id>.json.

    Args:
        base: diretório onde criar o raw
        convs: lista de dicts {"id", "updated_at", "title", ...}.
    """
    raw = base / "raw_DeepSeek"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "conversations").mkdir(exist_ok=True)
    (raw / "discovery_ids.json").write_text(
        json.dumps(convs, ensure_ascii=False),
        encoding="utf-8",
    )
    for c in convs:
        body = {"id": c["id"], "title": c.get("title"), "messages": []}
        (raw / "conversations" / f"{c['id']}.json").write_text(
            json.dumps(body, ensure_ascii=False),
            encoding="utf-8",
        )
    return raw


# === build_plan ===


class TestBuildPlanDeepSeek:
    def test_first_run_no_previous_all_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 1000.0, "title": "First"},
            {"id": "b", "updated_at": 2000.0, "title": "Second"},
        ])
        plan = build_plan(raw, previous_merged=None)
        assert sorted(plan.to_use) == ["a", "b"]
        assert plan.to_copy == []
        assert plan.preserved_missing == []

    def test_unchanged_goes_to_copy(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 1000.0, "title": "Same"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"id": "a", "updated_at": 1000.0, "title": "Same"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.to_copy == ["a"]
        assert plan.to_use == []
        assert plan.preserved_missing == []

    def test_updated_at_bumped_goes_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 2000.0, "title": "Updated"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"id": "a", "updated_at": 1000.0, "title": "Old"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.to_use == ["a"]
        assert plan.to_copy == []

    def test_title_changed_goes_to_use_even_if_updated_at_equal(self, tmp_path):
        """DeepSeek-specific: rename não bumpa updated_at — fallback no title."""
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 1000.0, "title": "Renamed"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"id": "a", "updated_at": 1000.0, "title": "Original"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.to_use == ["a"]

    def test_preserved_missing(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 1000.0, "title": "Active"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"id": "a", "updated_at": 1000.0, "title": "Active"},
            {"id": "b", "updated_at": 1500.0, "title": "Deleted"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.preserved_missing == ["b"]
        assert plan.to_copy == ["a"]


# === run_reconciliation ===


class TestRunReconciliationDeepSeek:
    def test_first_run_writes_outputs(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 1000.0, "title": "First"},
            {"id": "b", "updated_at": 2000.0, "title": "Second"},
        ])
        merged = tmp_path / "merged"
        report = run_reconciliation(raw, merged)
        assert report.added == 2
        assert report.updated == 0
        assert report.preserved_missing == 0
        # Estruturas de saida criadas
        assert (merged / "conversations" / "a.json").exists()
        assert (merged / "conversations" / "b.json").exists()
        assert (merged / "discovery_ids.json").exists()
        assert (merged / "deepseek_merged_summary.json").exists()
        assert (merged / "reconcile_log.jsonl").exists()
        assert (merged / "LAST_RECONCILE.md").exists()

    def test_preserved_marks_flag(self, tmp_path):
        # 1ª run
        raw1 = _make_raw_dir(tmp_path / "r1", [
            {"id": "a", "updated_at": 1000.0, "title": "X"},
            {"id": "b", "updated_at": 1500.0, "title": "Y"},
        ])
        merged = tmp_path / "merged"
        run_reconciliation(raw1, merged)

        # 2ª run: b sumiu
        raw2 = _make_raw_dir(tmp_path / "r2", [
            {"id": "a", "updated_at": 1000.0, "title": "X"},
        ])
        report = run_reconciliation(raw2, merged, previous_merged=merged)
        assert report.preserved_missing == 1
        # b agora deve ter _preserved_missing=True
        b = json.loads((merged / "conversations" / "b.json").read_text())
        assert b.get("_preserved_missing") is True

    def test_idempotent(self, tmp_path):
        """Rodar 2x consecutivas com mesmo raw produz mesmos parquets/jsons."""
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 1000.0, "title": "X"},
            {"id": "b", "updated_at": 2000.0, "title": "Y"},
        ])
        merged = tmp_path / "merged"

        run_reconciliation(raw, merged)
        snap = {
            f.name: f.read_bytes()
            for f in (merged / "conversations").glob("*.json")
        }
        snap["discovery"] = (merged / "discovery_ids.json").read_bytes()

        run_reconciliation(raw, merged, previous_merged=merged)
        for f in (merged / "conversations").glob("*.json"):
            assert f.read_bytes() == snap[f.name], f"{f.name} mudou na 2a run"
        assert (merged / "discovery_ids.json").read_bytes() == snap["discovery"]
