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

    def test_acquire_writes_started_at(self, _isolate_lock):
        from dashboard.sync import _read_lock, acquire_pipeline_lock, release_pipeline_lock

        acquire_pipeline_lock()
        data = _read_lock()
        assert "started_at" in data
        # Parsea sem erro
        from datetime import datetime
        datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
        release_pipeline_lock()

    def test_acquire_error_includes_age_when_lock_alive(self, _isolate_lock):
        from dashboard.sync import acquire_pipeline_lock, release_pipeline_lock

        acquire_pipeline_lock()
        err = acquire_pipeline_lock()
        assert err is not None
        # Idade aparece como "since Xs ago" / "since Xmin ago"
        assert "since" in err
        assert "ago" in err
        release_pipeline_lock()

    def test_acquire_error_without_started_at_omits_age(self, _isolate_lock):
        """Lockfile legado (sem started_at) — erro nao quebra, so nao mostra idade."""
        import json as _j
        from dashboard.sync import acquire_pipeline_lock, release_pipeline_lock

        _isolate_lock.write_text(_j.dumps({"parent_pid": os.getpid(), "child_pids": []}))
        err = acquire_pipeline_lock()
        assert err is not None
        # Sem started_at, sem ", since "
        assert "since" not in err
        release_pipeline_lock()

    def test_stale_lock_kills_orphan_children(self, _isolate_lock):
        from dashboard.sync import acquire_pipeline_lock, release_pipeline_lock

        # Simula crash com children registrados — PIDs fakes. _kill_process_tree
        # usa psutil; mockamos pra contar tentativas em cada PID orfao.
        _isolate_lock.write_text(
            json.dumps({"parent_pid": 999999, "child_pids": [888888, 777777]})
        )
        with patch("dashboard.sync._kill_process_tree") as mock_kill:
            err = acquire_pipeline_lock()
            assert err is None
            killed_pids = [call.args[0] for call in mock_kill.call_args_list]
            assert 888888 in killed_pids
            assert 777777 in killed_pids
        release_pipeline_lock()

    def test_kill_process_tree_terminates_subprocess(self):
        """End-to-end: psutil walk recursivo + SIGTERM no subprocess real."""
        import subprocess
        import time
        from dashboard.sync import _kill_process_tree

        p = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            time.sleep(0.1)
            assert p.poll() is None  # Vivo
            _kill_process_tree(p.pid)
            # Espera ate 2s pra SIGTERM propagar
            for _ in range(20):
                if p.poll() is not None:
                    break
                time.sleep(0.1)
            assert p.poll() is not None  # Morto
        finally:
            if p.poll() is None:
                p.kill()

    def test_kill_process_tree_terminates_playwright_chromium(self, tmp_path):
        """End-to-end com Playwright real: spawn chromium via Popen sub-Python,
        valida que ele tem filhos (chromium workers), mata via _kill_process_tree,
        confirma que todos descendentes morreram. Esse e o cenario real que
        a sessao Streamlit enfrenta quando crasha mid-sync.

        Skip se chromium nao esta instalado (CI sem `playwright install`)."""
        import subprocess
        import sys
        import time
        import psutil
        from dashboard.sync import _kill_process_tree

        # Subprocess que sobe Chromium e fica esperando — replica o que
        # `<plat>-export.py` faz quando o orchestrator esta em run.
        script = '''
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("about:blank")
        await asyncio.sleep(60)  # espera matar
asyncio.run(main())
'''
        # stderr=PIPE pra detectar "chromium nao instalado" e skipar
        # (CI sem `playwright install chromium`).
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            # Espera Chromium subir (chromium-headless-shell + helpers)
            time.sleep(3.0)
            if proc.poll() is not None:
                # Script morreu cedo. Le stderr pra distinguir 'chromium
                # nao instalado' (skip) de bug real (fail).
                try:
                    _, stderr_bytes = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stderr_bytes = b""
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")
                if "Executable doesn't exist" in stderr_text or "playwright install" in stderr_text.lower():
                    pytest.skip("Playwright chromium not installed (run `playwright install chromium`)")
                pytest.fail(f"Python script morreu cedo:\n{stderr_text[:1000]}")

            # Confirma que tem filhos antes do kill — psutil walk recursivo
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            assert len(children) > 0, (
                f"Esperava ao menos 1 filho Chromium, achei {len(children)}"
            )
            child_pids = [c.pid for c in children]

            # Mata a arvore
            _kill_process_tree(proc.pid)

            # Espera ate 5s pra SIGTERM propagar pelos descendentes
            for _ in range(50):
                if proc.poll() is not None:
                    # Parent morreu — checa que filhos tambem morreram
                    alive = [pid for pid in child_pids if psutil.pid_exists(pid)]
                    if not alive:
                        break
                time.sleep(0.1)

            # Validacao final
            assert proc.poll() is not None, "Parent Python ainda vivo"
            alive_children = [pid for pid in child_pids if psutil.pid_exists(pid)]
            assert not alive_children, (
                f"Chromium descendentes orfaos: {alive_children}"
            )
        finally:
            if proc.poll() is None:
                # Last resort cleanup
                try:
                    parent = psutil.Process(proc.pid)
                    for c in parent.children(recursive=True):
                        try:
                            c.kill()
                        except psutil.NoSuchProcess:
                            pass
                    parent.kill()
                except psutil.NoSuchProcess:
                    pass


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

    def test_commit_msg_for_scope_all(self):
        from dashboard.pipeline import commit_msg_for_scope

        msg = commit_msg_for_scope("all")
        assert msg.startswith("data: dashboard sync (all platforms, ")
        assert msg.endswith(")")

    def test_commit_msg_for_scope_platform(self):
        from dashboard.pipeline import commit_msg_for_scope

        assert "(NotebookLM, " in commit_msg_for_scope("platform:NotebookLM")
        assert "(Claude.ai, " in commit_msg_for_scope("platform:Claude.ai")

    def test_commit_msg_for_scope_cli_headless(self):
        from dashboard.pipeline import commit_msg_for_scope

        msg = commit_msg_for_scope("cli:headless")
        assert msg.startswith("data: headless sync (")

    def test_commit_msg_for_scope_unknown_fallback(self):
        from dashboard.pipeline import commit_msg_for_scope

        msg = commit_msg_for_scope("custom-scope")
        assert "custom-scope" in msg
        assert msg.startswith("data: pipeline sync")

    def test_rotation_truncates_after_max(self, _isolate_runs_log, monkeypatch):
        """Quando ultrapassa MAX_RUNS_BEFORE_ROTATE, trunca pra KEEP_RUNS_AFTER_ROTATE."""
        from dashboard import pipeline as pl
        from dashboard.pipeline import persist_run, recent_runs

        # Usa thresholds pequenos pra teste rapido
        monkeypatch.setattr(pl, "MAX_RUNS_BEFORE_ROTATE", 10)
        monkeypatch.setattr(pl, "KEEP_RUNS_AFTER_ROTATE", 5)

        # Escreve 9 — ainda nao rotaciona
        for i in range(9):
            persist_run(["done"] * 4, [], True, scope=f"r-{i}")
        with _isolate_runs_log.open() as f:
            assert len(f.readlines()) == 9

        # Escreve a 10a — ainda nao (threshold eh > 10)
        persist_run(["done"] * 4, [], True, scope="r-9")
        with _isolate_runs_log.open() as f:
            assert len(f.readlines()) == 10

        # 11a — ultrapassa, rotaciona pra 5
        persist_run(["done"] * 4, [], True, scope="r-10")
        with _isolate_runs_log.open() as f:
            lines = f.readlines()
        assert len(lines) == 5
        # Mantem as ultimas (mais recentes)
        scopes = [json.loads(l)["scope"] for l in lines]
        assert scopes == ["r-6", "r-7", "r-8", "r-9", "r-10"]

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
