"""Tests dos novos helpers do pipeline (Stage 3 incremental, persist runs,
lockfile JSON com child cleanup)."""
from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest


# ===================== Stage 3 incremental =====================


class TestDiscoverQmdsFilter:
    def test_no_filter_returns_all_non_template_qmds(self):
        from dashboard.sync import discover_qmds

        result = discover_qmds()
        names = {p.name for p in result}
        # Sanity: pelo menos os principais existem
        assert "chatgpt.qmd" in names
        assert "00-overview.qmd" in names
        # Templates filtrados
        assert "_template.qmd" not in names
        assert "_template_aux.qmd" not in names

    def test_filter_returns_platform_qmds_plus_overviews(self):
        from dashboard.sync import discover_qmds

        result = discover_qmds(platforms_filter=["NotebookLM"])
        names = {p.name for p in result}
        # NotebookLM consolidado + per-account + legacy
        assert "notebooklm.qmd" in names
        assert "notebooklm-acc-1.qmd" in names
        assert "notebooklm-acc-2.qmd" in names
        assert "notebooklm-legacy.qmd" in names
        # Sempre inclui cross-overview
        assert "00-overview.qmd" in names
        assert "00-overview-rag.qmd" in names
        # NAO inclui qmds de outras plats
        assert "chatgpt.qmd" not in names
        assert "claude-ai.qmd" not in names

    def test_filter_chatgpt_only_consolidated(self):
        """ChatGPT nao tem per-account — so consolidado + cross-overview."""
        from dashboard.sync import discover_qmds

        result = discover_qmds(platforms_filter=["ChatGPT"])
        names = {p.name for p in result}
        assert "chatgpt.qmd" in names
        assert "00-overview.qmd" in names
        # Sem chatgpt-acc-X.qmd existente
        assert not any("chatgpt-acc" in n for n in names)

    def test_filter_unknown_plat_returns_only_overviews(self):
        """Plat sem qmd no disco: result tem so os overviews."""
        from dashboard.sync import discover_qmds

        result = discover_qmds(platforms_filter=["NonexistentPlat"])
        names = {p.name for p in result}
        assert all(n.startswith("00-") for n in names)

    def test_overview_qmds_come_first(self):
        from dashboard.sync import discover_qmds

        result = discover_qmds(platforms_filter=["Gemini"])
        # 00-* primeiro, depois alfabetico
        first_non_overview = next(
            (p for p in result if not p.name.startswith("00-")), None
        )
        assert first_non_overview is not None
        # Garante que vem depois de todos 00-*
        overview_idx = [i for i, p in enumerate(result) if p.name.startswith("00-")]
        non_overview_idx = result.index(first_non_overview)
        assert all(i < non_overview_idx for i in overview_idx)


class TestQmdsForPlatform:
    def test_consolidated_only(self):
        from dashboard.quarto import qmds_for_platform

        result = qmds_for_platform("ChatGPT")
        names = [p.name for p in result]
        assert "chatgpt.qmd" in names

    def test_includes_per_account(self):
        from dashboard.quarto import qmds_for_platform

        result = qmds_for_platform("NotebookLM")
        names = [p.name for p in result]
        assert "notebooklm.qmd" in names
        assert "notebooklm-acc-1.qmd" in names
        assert "notebooklm-acc-2.qmd" in names
        assert "notebooklm-legacy.qmd" in names

    def test_unknown_platform_returns_empty(self):
        from dashboard.quarto import qmds_for_platform

        assert qmds_for_platform("Nonexistent") == []


# ===================== Lockfile JSON =====================


class TestLockfile:
    """Lockfile mantem estado entre runs do pipeline: parent + children orfaos.

    Tests usam tmp_path pra isolar do .update-all.lock real do repo."""

    @pytest.fixture(autouse=True)
    def _isolate_lock(self, tmp_path, monkeypatch):
        # Patch LOCK_PATH pra arquivo temporario — nao bagunca o lock real
        lock = tmp_path / ".test-lock"
        monkeypatch.setattr("dashboard.sync.LOCK_PATH", lock)
        yield lock

    def test_fresh_acquire_writes_json(self, _isolate_lock):
        from dashboard.sync import _read_lock, acquire_pipeline_lock, release_pipeline_lock

        err = acquire_pipeline_lock()
        assert err is None
        data = _read_lock()
        assert data["parent_pid"] == os.getpid()
        assert data["child_pids"] == []
        release_pipeline_lock()
        assert not _isolate_lock.exists()

    def test_double_acquire_blocked_if_pid_alive(self, _isolate_lock):
        from dashboard.sync import acquire_pipeline_lock, release_pipeline_lock

        assert acquire_pipeline_lock() is None
        err = acquire_pipeline_lock()
        assert err is not None
        assert "already running" in err.lower()
        release_pipeline_lock()

    def test_stale_lock_with_dead_parent_acquired(self, _isolate_lock):
        from dashboard.sync import _read_lock, acquire_pipeline_lock, release_pipeline_lock

        # PID 999999 nao existe — simula crash
        _isolate_lock.write_text(json.dumps({"parent_pid": 999999, "child_pids": []}))
        err = acquire_pipeline_lock()
        assert err is None
        data = _read_lock()
        assert data["parent_pid"] == os.getpid()
        release_pipeline_lock()

    def test_legacy_int_lockfile_compat(self, _isolate_lock):
        from dashboard.sync import _read_lock

        _isolate_lock.write_text(str(os.getpid()))
        data = _read_lock()
        assert data["parent_pid"] == os.getpid()
        assert data["child_pids"] == []

    def test_register_unregister_child(self, _isolate_lock):
        from dashboard.sync import (
            _read_lock,
            _register_child,
            _unregister_child,
            acquire_pipeline_lock,
            release_pipeline_lock,
        )

        acquire_pipeline_lock()
        _register_child(12345)
        _register_child(12346)
        assert _read_lock()["child_pids"] == [12345, 12346]
        _unregister_child(12345)
        assert _read_lock()["child_pids"] == [12346]
        release_pipeline_lock()

    def test_stale_lock_kills_orphan_children(self, _isolate_lock):
        from dashboard.sync import acquire_pipeline_lock, release_pipeline_lock

        # Simula crash com children registrados — PIDs fakes, killpg vira no-op
        _isolate_lock.write_text(
            json.dumps({"parent_pid": 999999, "child_pids": [888888, 777777]})
        )
        with patch("dashboard.sync.os.killpg") as mock_killpg:
            mock_killpg.side_effect = ProcessLookupError  # PIDs ja morreram
            err = acquire_pipeline_lock()
            assert err is None
            # Tentou matar os dois
            killed_pids = [call.args[0] for call in mock_killpg.call_args_list]
            assert 888888 in killed_pids
            assert 777777 in killed_pids
        release_pipeline_lock()


# ===================== Persist runs =====================


class TestPersistRuns:
    @pytest.fixture(autouse=True)
    def _isolate_runs_log(self, tmp_path, monkeypatch):
        log = tmp_path / ".test-runs.jsonl"
        monkeypatch.setattr("dashboard.pipeline.RUNS_LOG", log)
        yield log

    def test_persist_appends_entry(self, _isolate_runs_log):
        from dashboard.pipeline import persist_run, recent_runs

        persist_run(
            stage_status=["done", "done", "done", "done"],
            results=[
                {"stage": "1/4 Sync", "step": "ChatGPT", "status": "ok",
                 "detail": "", "tail": "should be stripped"}
            ],
            publish_after=True,
            scope="all",
        )
        runs = recent_runs(10)
        assert len(runs) == 1
        entry = runs[0]
        assert entry["scope"] == "all"
        assert entry["stage_status"] == ["done", "done", "done", "done"]
        # Tail removido (so metadata persiste)
        assert "tail" not in entry["results"][0]

    def test_recent_runs_returns_newest_first(self, _isolate_runs_log):
        from dashboard.pipeline import persist_run, recent_runs

        persist_run(["done"] * 4, [], True, scope="first")
        persist_run(["done"] * 4, [], True, scope="second")
        persist_run(["done"] * 4, [], True, scope="third")
        runs = recent_runs(10)
        assert [r["scope"] for r in runs] == ["third", "second", "first"]

    def test_recent_runs_limit(self, _isolate_runs_log):
        from dashboard.pipeline import persist_run, recent_runs

        for i in range(15):
            persist_run(["done"] * 4, [], True, scope=f"run-{i}")
        runs = recent_runs(limit=5)
        assert len(runs) == 5
        # Os 5 mais recentes (14, 13, 12, 11, 10)
        assert [r["scope"] for r in runs] == [f"run-{i}" for i in (14, 13, 12, 11, 10)]

    def test_recent_runs_empty_when_no_log(self, _isolate_runs_log):
        from dashboard.pipeline import recent_runs

        # Sem chamar persist_run primeiro
        assert recent_runs() == []

    def test_recent_runs_handles_corrupt_lines(self, _isolate_runs_log):
        from dashboard.pipeline import recent_runs

        _isolate_runs_log.write_text(
            json.dumps({"scope": "ok-1", "at": "2026-01-01T00:00:00Z",
                        "stage_status": [], "publish": True, "results": []}) + "\n"
            + "NOT JSON\n"
            + json.dumps({"scope": "ok-2", "at": "2026-01-02T00:00:00Z",
                          "stage_status": [], "publish": True, "results": []}) + "\n"
        )
        runs = recent_runs()
        # Linha corrupta pulada, 2 validas mantidas
        assert len(runs) == 2
        assert {r["scope"] for r in runs} == {"ok-1", "ok-2"}
