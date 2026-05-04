"""Smoke tests pro reconciler Perplexity.

Schema: threads via `uuid` + `last_query_datetime` (ISO) + `query_count` +
`title`. Spaces opcionais. Refetch dispara em mudança de
last_query_datetime, query_count incrementado, ou rename.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.reconcilers.perplexity import build_plan, run_reconciliation


def _make_raw_dir(base: Path, threads: list[dict]) -> Path:
    """Args: threads = lista de
    {"uuid", "last_query_datetime" (ISO), "query_count", "title"}.
    """
    raw = base / "raw_Perplexity"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "threads").mkdir(exist_ok=True)
    (raw / "discovery_ids.json").write_text(
        json.dumps(threads, ensure_ascii=False),
        encoding="utf-8",
    )
    for t in threads:
        body = {"uuid": t["uuid"], "title": t.get("title"), "blocks": []}
        (raw / "threads" / f"{t['uuid']}.json").write_text(
            json.dumps(body, ensure_ascii=False),
            encoding="utf-8",
        )
    return raw


class TestBuildPlanPerplexity:
    def test_first_run_all_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "First"},
            {"uuid": "u2", "last_query_datetime": "2026-01-02T00:00:00Z",
             "query_count": 5, "title": "Second"},
        ])
        plan = build_plan(raw, previous_merged=None)
        assert sorted(plan.threads_to_use) == ["u1", "u2"]
        assert plan.threads_to_copy == []

    def test_unchanged_goes_to_copy(self, tmp_path):
        thread = {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
                  "query_count": 3, "title": "X"}
        raw = _make_raw_dir(tmp_path, [thread])
        prev = _make_raw_dir(tmp_path / "prev", [thread])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.threads_to_copy == ["u1"]

    def test_query_count_incremented_goes_to_use(self, tmp_path):
        """Perplexity-specific: incremento em query_count força refetch
        (mais querys novas na thread)."""
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 5, "title": "X"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "X"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.threads_to_use == ["u1"]

    def test_last_query_datetime_bumped(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "last_query_datetime": "2026-01-15T00:00:00Z",
             "query_count": 3, "title": "X"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "X"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.threads_to_use == ["u1"]

    def test_title_changed_goes_to_use(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "Renamed"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "Original"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.threads_to_use == ["u1"]

    def test_preserved_missing(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "Active"},
        ])
        prev = _make_raw_dir(tmp_path / "prev", [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "Active"},
            {"uuid": "u2", "last_query_datetime": "2026-01-02T00:00:00Z",
             "query_count": 1, "title": "Deleted"},
        ])
        plan = build_plan(raw, previous_merged=prev)
        assert plan.threads_preserved_missing == ["u2"]


class TestRunReconciliationPerplexity:
    def test_first_run_writes_outputs(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "X"},
        ])
        merged = tmp_path / "merged"
        report = run_reconciliation(raw, merged)
        assert report.threads_added == 1
        assert (merged / "threads" / "u1.json").exists()
        assert (merged / "threads_discovery.json").exists() or \
               (merged / "discovery_ids.json").exists()

    def test_idempotent(self, tmp_path):
        raw = _make_raw_dir(tmp_path, [
            {"uuid": "u1", "last_query_datetime": "2026-01-01T00:00:00Z",
             "query_count": 3, "title": "X"},
        ])
        merged = tmp_path / "merged"
        run_reconciliation(raw, merged)
        snap = (merged / "threads" / "u1.json").read_bytes()
        run_reconciliation(raw, merged, previous_merged=merged)
        assert (merged / "threads" / "u1.json").read_bytes() == snap
