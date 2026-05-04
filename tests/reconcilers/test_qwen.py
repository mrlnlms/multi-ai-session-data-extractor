"""Smoke tests pro reconciler Qwen.

Cobre os 5 cenários canônicos. Qwen tem schema similar ao DeepSeek
(threads via `id` + `updated_at` + `title`) mas adiciona projects opcionais.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.reconcilers.qwen import build_plan, run_reconciliation


def _make_raw_dir(base: Path, convs: list[dict]) -> Path:
    raw = base / "raw_Qwen"
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


class TestBuildPlanQwen:
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

    def test_updated_at_bumped_goes_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 2000.0, "title": "X"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"id": "a", "updated_at": 1000.0, "title": "X"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.to_use == ["a"]

    def test_title_changed_goes_to_use(self, tmp_path):
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


class TestRunReconciliationQwen:
    def test_first_run_writes_outputs(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 1000.0, "title": "X"},
        ])
        merged = tmp_path / "merged"
        report = run_reconciliation(raw, merged)
        assert report.added == 1
        assert (merged / "conversations" / "a.json").exists()
        assert (merged / "discovery_ids.json").exists()
        assert (merged / "qwen_merged_summary.json").exists()
        assert (merged / "LAST_RECONCILE.md").exists()

    def test_preserved_marks_flag(self, tmp_path):
        raw1 = _make_raw_dir(tmp_path / "r1", [
            {"id": "a", "updated_at": 1000.0, "title": "X"},
            {"id": "b", "updated_at": 1500.0, "title": "Y"},
        ])
        merged = tmp_path / "merged"
        run_reconciliation(raw1, merged)

        raw2 = _make_raw_dir(tmp_path / "r2", [
            {"id": "a", "updated_at": 1000.0, "title": "X"},
        ])
        report = run_reconciliation(raw2, merged, previous_merged=merged)
        assert report.preserved_missing == 1
        b = json.loads((merged / "conversations" / "b.json").read_text())
        assert b.get("_preserved_missing") is True

    def test_idempotent(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"id": "a", "updated_at": 1000.0, "title": "X"},
        ])
        merged = tmp_path / "merged"
        run_reconciliation(raw, merged)
        snap_a = (merged / "conversations" / "a.json").read_bytes()
        snap_d = (merged / "discovery_ids.json").read_bytes()

        run_reconciliation(raw, merged, previous_merged=merged)
        assert (merged / "conversations" / "a.json").read_bytes() == snap_a
        assert (merged / "discovery_ids.json").read_bytes() == snap_d
