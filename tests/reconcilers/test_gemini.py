"""Smoke tests pro reconciler Gemini.

Schema: `uuid` (não `id`), `created_at_secs` (não `updated_at`), e `pinned`
adicional ao title. Detecta refetch via title OU pinned change.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.reconcilers.gemini import build_plan, run_reconciliation


def _make_raw_dir(base: Path, convs: list[dict]) -> Path:
    """Args: convs = lista de {"uuid", "created_at_secs", "title", "pinned"?}."""
    raw = base / "raw_Gemini"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "conversations").mkdir(exist_ok=True)
    (raw / "discovery_ids.json").write_text(
        json.dumps(convs, ensure_ascii=False),
        encoding="utf-8",
    )
    for c in convs:
        body = {"uuid": c["uuid"], "title": c.get("title")}
        (raw / "conversations" / f"{c['uuid']}.json").write_text(
            json.dumps(body, ensure_ascii=False),
            encoding="utf-8",
        )
    return raw


class TestBuildPlanGemini:
    def test_first_run_all_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "created_at_secs": 1000, "title": "First"},
            {"uuid": "u2", "created_at_secs": 2000, "title": "Second"},
        ])
        plan = build_plan(raw, previous_merged=None)
        assert sorted(plan.to_use) == ["u1", "u2"]

    def test_unchanged_goes_to_copy(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "created_at_secs": 1000, "title": "X", "pinned": False},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "created_at_secs": 1000, "title": "X", "pinned": False},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.to_copy == ["u1"]

    def test_pinned_changed_goes_to_use(self, tmp_path):
        """Gemini-specific: mudança de pin força refetch."""
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "created_at_secs": 1000, "title": "X", "pinned": True},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "created_at_secs": 1000, "title": "X", "pinned": False},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.to_use == ["u1"]

    def test_title_changed_goes_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "created_at_secs": 1000, "title": "Renamed"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "created_at_secs": 1000, "title": "Original"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.to_use == ["u1"]

    def test_preserved_missing(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "created_at_secs": 1000, "title": "Active"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "created_at_secs": 1000, "title": "Active"},
            {"uuid": "u2", "created_at_secs": 2000, "title": "Deleted"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.preserved_missing == ["u2"]


class TestRunReconciliationGemini:
    def test_first_run_writes_outputs(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "created_at_secs": 1000, "title": "X"},
        ])
        merged = tmp_path / "merged"
        report = run_reconciliation(raw, merged)
        assert report.added == 1
        assert (merged / "conversations" / "u1.json").exists()
        assert (merged / "discovery_ids.json").exists()

    def test_preserved_marks_flag(self, tmp_path):
        raw1 = _make_raw_dir(tmp_path / "r1", [
            {"uuid": "u1", "created_at_secs": 1000, "title": "X"},
            {"uuid": "u2", "created_at_secs": 1500, "title": "Y"},
        ])
        merged = tmp_path / "merged"
        run_reconciliation(raw1, merged)

        raw2 = _make_raw_dir(tmp_path / "r2", [
            {"uuid": "u1", "created_at_secs": 1000, "title": "X"},
        ])
        report = run_reconciliation(raw2, merged, previous_merged=merged)
        assert report.preserved_missing == 1
        u2 = json.loads((merged / "conversations" / "u2.json").read_text())
        assert u2.get("_preserved_missing") is True

    def test_idempotent(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "created_at_secs": 1000, "title": "X"},
        ])
        merged = tmp_path / "merged"
        run_reconciliation(raw, merged)
        snap = (merged / "conversations" / "u1.json").read_bytes()
        run_reconciliation(raw, merged, previous_merged=merged)
        assert (merged / "conversations" / "u1.json").read_bytes() == snap
