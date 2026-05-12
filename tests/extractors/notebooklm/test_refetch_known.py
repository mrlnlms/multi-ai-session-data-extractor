"""Testes do refetch_known NotebookLM (fallback de discovery parcial).

Cobre:
- _load_known_notebooks: le UUIDs dos notebooks salvos no raw cumulativo,
  pula auxiliares (mind_map_tree).
- refetch_known_notebooklm: composite fetch usa fetch_notebook do fetcher
  (nao duplica logica), conta updated/errors corretamente.
- Orchestrator fallback: quando discovery cai >threshold, dispara refetch_known
  em vez de raise RuntimeError, grava log_entry com mode=refetch_known_fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.extractors.notebooklm.refetch_known import (
    _is_uuid,
    _load_known_notebooks,
    refetch_known_notebooklm,
)


def _make_raw(account_dir: Path, uuid: str, title: str) -> None:
    """Cria um notebook json minimo em notebooks/<uuid>.json."""
    nb_dir = account_dir / "notebooks"
    nb_dir.mkdir(parents=True, exist_ok=True)
    raw = {
        "metadata": None,
        "guide": None,
        "chat": None,
        "notes": None,
        "audios": None,
        "mind_map": None,
        "uuid": uuid,
        "title": title,
    }
    (nb_dir / f"{uuid}.json").write_text(json.dumps(raw), encoding="utf-8")


class TestIsUuid:
    def test_valid_uuid(self):
        assert _is_uuid("02f39aab-f3c9-4162-84fe-0f5b31d5d734")

    def test_too_short(self):
        assert not _is_uuid("abc-def")

    def test_no_dashes(self):
        assert not _is_uuid("02f39aabf3c9416284fe0f5b31d5d7340000")  # sem hifens


class TestLoadKnownNotebooks:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert _load_known_notebooks(tmp_path) == []

    def test_reads_uuid_and_title(self, tmp_path):
        _make_raw(tmp_path, "02f39aab-f3c9-4162-84fe-0f5b31d5d734", "Estapar 3")
        _make_raw(tmp_path, "03009b16-b3b0-4c8b-98e9-e8dd1cc5d686", "Outro")
        result = _load_known_notebooks(tmp_path)
        assert sorted(result) == [
            ("02f39aab-f3c9-4162-84fe-0f5b31d5d734", "Estapar 3"),
            ("03009b16-b3b0-4c8b-98e9-e8dd1cc5d686", "Outro"),
        ]

    def test_skips_mind_map_tree_files(self, tmp_path):
        """Aux files (`*_mind_map_tree.json`) nao entram na lista."""
        _make_raw(tmp_path, "02f39aab-f3c9-4162-84fe-0f5b31d5d734", "NB")
        # Cria mind_map_tree aux
        (tmp_path / "notebooks" / "02f39aab-f3c9-4162-84fe-0f5b31d5d734_mind_map_tree.json").write_text(
            json.dumps({"raw": []}), encoding="utf-8"
        )
        result = _load_known_notebooks(tmp_path)
        assert result == [("02f39aab-f3c9-4162-84fe-0f5b31d5d734", "NB")]


class TestRefetchKnownNotebooklm:
    async def test_empty_returns_zero(self, tmp_path):
        """Sem notebooks conhecidos: total=0 e nao chama fetch."""
        result = await refetch_known_notebooklm(client=None, account_dir=tmp_path)
        assert result == {"total": 0, "updated": 0, "errors": 0}

    async def test_composite_fetch_uses_fetcher(self, tmp_path, mocker):
        """Pra cada notebook reusa fetch_notebook (nao re-implementa fetch_*)."""
        _make_raw(tmp_path, "uuid-a-1234-5678-9abc-def012345678", "NB-A")
        _make_raw(tmp_path, "uuid-b-1234-5678-9abc-def012345678", "NB-B")

        mock_fetch = mocker.patch(
            "src.extractors.notebooklm.refetch_known.fetch_notebook",
            new_callable=mocker.AsyncMock,
            return_value={
                "rpcs_errors": [], "sources_fetched": 0, "n_source_uuids": 0,
            },
        )

        result = await refetch_known_notebooklm(client=mocker.MagicMock(), account_dir=tmp_path)
        assert result["total"] == 2
        assert result["updated"] == 2
        assert result["errors"] == 0
        assert mock_fetch.call_count == 2

    async def test_counts_errors_per_notebook(self, tmp_path, mocker):
        """Notebook com rpcs_errors conta como error, sem rpcs_errors conta como updated."""
        _make_raw(tmp_path, "uuid-a-1234-5678-9abc-def012345678", "A")
        _make_raw(tmp_path, "uuid-b-1234-5678-9abc-def012345678", "B")

        call_results = [
            {"rpcs_errors": [], "sources_fetched": 0, "n_source_uuids": 0},
            {"rpcs_errors": [("metadata", "boom")], "sources_fetched": 0, "n_source_uuids": 0},
        ]
        mocker.patch(
            "src.extractors.notebooklm.refetch_known.fetch_notebook",
            new_callable=mocker.AsyncMock,
            side_effect=call_results,
        )

        result = await refetch_known_notebooklm(client=mocker.MagicMock(), account_dir=tmp_path)
        assert result["total"] == 2
        assert result["updated"] == 1
        assert result["errors"] == 1

    async def test_exception_increments_errors(self, tmp_path, mocker):
        """Exception no fetch nao para o loop — incrementa errors."""
        _make_raw(tmp_path, "uuid-a-1234-5678-9abc-def012345678", "A")
        _make_raw(tmp_path, "uuid-b-1234-5678-9abc-def012345678", "B")

        async def _flaky(client, uuid, title, account_dir, source_concurrency=2):
            if "uuid-a" in uuid:
                raise RuntimeError("network blip")
            return {"rpcs_errors": [], "sources_fetched": 0, "n_source_uuids": 0}

        mocker.patch(
            "src.extractors.notebooklm.refetch_known.fetch_notebook",
            side_effect=_flaky,
        )
        result = await refetch_known_notebooklm(client=mocker.MagicMock(), account_dir=tmp_path)
        assert result["total"] == 2
        assert result["updated"] == 1
        assert result["errors"] == 1


class TestOrchestratorFallback:
    """Quando discovery cai >threshold, orchestrator NAO raise — chama refetch_known."""

    async def test_drop_dispatches_refetch_and_logs_mode(self, tmp_path, mocker):
        from src.extractors.notebooklm import orchestrator as orch

        # Setup raw cumulativo per-account com baseline historico alto
        account_dir = tmp_path / "account-1"
        account_dir.mkdir(parents=True)
        log = account_dir / "capture_log.jsonl"
        log.write_text(
            json.dumps({"totals": {"notebooks_discovered": 100}}) + "\n",
            encoding="utf-8",
        )
        # Coloca 1 notebook conhecido pra o refetch ter o que processar
        _make_raw(account_dir, "uuid-a-1234-5678-9abc-def012345678", "NB-A")

        # Mock BASE_DIR pra apontar pro tmp_path
        mocker.patch.object(orch, "BASE_DIR", tmp_path)

        # Mock auth/session/discovery/refetch
        ctx_mock = mocker.AsyncMock()
        mocker.patch.object(orch, "load_context", new_callable=mocker.AsyncMock, return_value=ctx_mock)
        mocker.patch.object(orch, "load_session", new_callable=mocker.AsyncMock, return_value={})
        mocker.patch.object(orch, "NotebookLMClient", return_value=mocker.MagicMock())
        # Discovery vem com 10 (queda de 90% > threshold 20%)
        mocker.patch.object(
            orch, "discover", new_callable=mocker.AsyncMock,
            return_value=[{"uuid": "x", "title": "x"}] * 10,
        )

        refetch_mock = mocker.patch.object(
            orch, "refetch_known_notebooklm", new_callable=mocker.AsyncMock,
            return_value={"total": 1, "updated": 1, "errors": 0},
        )

        result = await orch.run_export(account="1")

        # Refetch foi chamado e o log ganhou mode=refetch_known_fallback
        refetch_mock.assert_awaited_once()
        log_lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert len(log_lines) == 2  # baseline + nova entry
        new_entry = json.loads(log_lines[-1])
        assert new_entry["mode"] == "refetch_known_fallback"
        assert new_entry["totals"]["notebooks_fetched"] == 1
        assert result == account_dir

    async def test_no_drop_skips_refetch(self, tmp_path, mocker):
        """Sem queda, refetch_known NAO eh chamado — fluxo normal segue."""
        from src.extractors.notebooklm import orchestrator as orch

        account_dir = tmp_path / "account-1"
        account_dir.mkdir(parents=True)
        log = account_dir / "capture_log.jsonl"
        log.write_text(
            json.dumps({"totals": {"notebooks_discovered": 10}}) + "\n",
            encoding="utf-8",
        )

        mocker.patch.object(orch, "BASE_DIR", tmp_path)
        ctx_mock = mocker.AsyncMock()
        mocker.patch.object(orch, "load_context", new_callable=mocker.AsyncMock, return_value=ctx_mock)
        mocker.patch.object(orch, "load_session", new_callable=mocker.AsyncMock, return_value={})
        mocker.patch.object(orch, "NotebookLMClient", return_value=mocker.MagicMock())
        mocker.patch.object(
            orch, "discover", new_callable=mocker.AsyncMock,
            return_value=[{"uuid": f"u-{i}", "title": f"t-{i}"} for i in range(10)],
        )
        mocker.patch.object(orch, "persist_discovery")
        mocker.patch.object(
            orch, "fetch_notebook", new_callable=mocker.AsyncMock,
            return_value={
                "rpcs_ok": 6, "rpcs_empty": 0, "rpcs_errors": [],
                "sources_fetched": 0, "n_source_uuids": 0, "sources_errors": [],
                "artifacts_fetched_individual": 0, "mind_map_fetched": False,
            },
        )
        refetch_mock = mocker.patch.object(
            orch, "refetch_known_notebooklm", new_callable=mocker.AsyncMock,
        )

        await orch.run_export(account="1")
        refetch_mock.assert_not_awaited()
