"""Smoke tests pro reconciler Claude.ai.

Schema único entre os reconcilers: tem `conversations` E `projects` no
mesmo discovery_ids.json. Campos: `uuid` + `updated_at` (ISO string) +
`name` (não `title`).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.reconcilers.claude_ai import build_plan, run_reconciliation


def _make_raw_dir(
    base: Path,
    convs: list[dict],
    projects: list[dict] | None = None,
) -> Path:
    """Cria raw_dir Claude.ai mínimo.

    Args:
        convs: lista de {"uuid", "updated_at" ISO, "name"}.
        projects: idem (opcional).
    """
    raw = base / "raw_ClaudeAI"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "conversations").mkdir(exist_ok=True)
    (raw / "projects").mkdir(exist_ok=True)

    discovery = {"conversations": convs, "projects": projects or []}
    (raw / "discovery_ids.json").write_text(
        json.dumps(discovery, ensure_ascii=False),
        encoding="utf-8",
    )
    for c in convs:
        body = {"uuid": c["uuid"], "name": c.get("name"), "chat_messages": []}
        (raw / "conversations" / f"{c['uuid']}.json").write_text(
            json.dumps(body, ensure_ascii=False),
            encoding="utf-8",
        )
    for p in (projects or []):
        body = {"uuid": p["uuid"], "name": p.get("name")}
        (raw / "projects" / f"{p['uuid']}.json").write_text(
            json.dumps(body, ensure_ascii=False),
            encoding="utf-8",
        )
    return raw


class TestBuildPlanClaudeAI:
    def test_first_run_all_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "First"},
            {"uuid": "u2", "updated_at": "2026-01-02T00:00:00Z", "name": "Second"},
        ])
        plan = build_plan(raw, previous_merged=None)
        assert sorted(plan.convs_to_use) == ["u1", "u2"]
        assert plan.convs_to_copy == []
        assert plan.convs_preserved_missing == []

    def test_unchanged_goes_to_copy(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "X"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "X"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.convs_to_copy == ["u1"]

    def test_updated_at_iso_lexicographic(self, tmp_path):
        """Claude.ai usa ISO timestamp; ordenação lexicográfica funciona pra ISO."""
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "updated_at": "2026-01-15T00:00:00Z", "name": "X"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "X"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.convs_to_use == ["u1"]

    def test_name_changed_goes_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "Renamed"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "Original"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.convs_to_use == ["u1"]

    def test_preserved_missing_per_kind(self, tmp_path):
        """convs e projects são tratados separadamente."""
        raw = _make_raw_dir(
            tmp_path,
            convs=[{"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "Active"}],
            projects=[{"uuid": "p1", "updated_at": "2026-01-01T00:00:00Z", "name": "ProjA"}],
        )
        prev = _make_raw_dir(
            tmp_path / "prev",
            convs=[
                {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "Active"},
                {"uuid": "u2", "updated_at": "2026-01-01T00:00:00Z", "name": "Deleted"},
            ],
            projects=[
                {"uuid": "p1", "updated_at": "2026-01-01T00:00:00Z", "name": "ProjA"},
                {"uuid": "p2", "updated_at": "2026-01-01T00:00:00Z", "name": "ProjDel"},
            ],
        )
        plan = build_plan(raw, previous_merged=prev)
        assert plan.convs_preserved_missing == ["u2"]
        assert plan.projects_preserved_missing == ["p2"]


class TestRunReconciliationClaudeAI:
    def test_first_run_writes_outputs(self, tmp_path):
        raw = _make_raw_dir(
            tmp_path,
            convs=[{"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "X"}],
            projects=[{"uuid": "p1", "updated_at": "2026-01-01T00:00:00Z", "name": "ProjA"}],
        )
        merged = tmp_path / "merged"
        report = run_reconciliation(raw, merged)
        assert report.convs_added == 1
        assert report.projects_added == 1
        assert (merged / "conversations" / "u1.json").exists()
        assert (merged / "projects" / "p1.json").exists()
        assert (merged / "claude_ai_merged_summary.json").exists()
        assert (merged / "LAST_RECONCILE.md").exists()

    def test_preserved_marks_flag(self, tmp_path):
        raw1 = _make_raw_dir(tmp_path / "r1", [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "X"},
            {"uuid": "u2", "updated_at": "2026-01-01T00:00:00Z", "name": "Y"},
        ])
        merged = tmp_path / "merged"
        run_reconciliation(raw1, merged)

        raw2 = _make_raw_dir(tmp_path / "r2", [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "X"},
        ])
        report = run_reconciliation(raw2, merged, previous_merged=merged)
        assert report.convs_preserved_missing == 1
        u2 = json.loads((merged / "conversations" / "u2.json").read_text())
        assert u2.get("_preserved_missing") is True

    def test_idempotent(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "updated_at": "2026-01-01T00:00:00Z", "name": "X"},
        ])
        merged = tmp_path / "merged"
        run_reconciliation(raw, merged)
        snap = (merged / "conversations" / "u1.json").read_bytes()
        run_reconciliation(raw, merged, previous_merged=merged)
        assert (merged / "conversations" / "u1.json").read_bytes() == snap
