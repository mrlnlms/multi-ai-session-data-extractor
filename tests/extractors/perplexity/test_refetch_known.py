"""Testes do refetch_known fallback Perplexity.

Quando discovery /rest/thread/list_ask_threads retorna parcial, orchestrator
cai pra refetch_known_perplexity, que junta UUIDs do raw cumulativo
(discovery_ids.json + threads/*.json) e refresca cada thread via
client.fetch_thread(uuid).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.extractors.perplexity.refetch_known import (
    _collect_known_uuids,
    refetch_known_perplexity,
)


class _FakeClient:
    """Stub de PerplexityAPIClient.fetch_thread.

    `raise_for` permite simular erro pra UUIDs especificos (testa errors count).
    """

    def __init__(self, raise_for: set[str] | None = None):
        self.raise_for = raise_for or set()
        self.calls: list[str] = []

    async def fetch_thread(self, uuid: str) -> dict:
        self.calls.append(uuid)
        if uuid in self.raise_for:
            raise RuntimeError(f"simulado: HTTP 500 on /rest/thread/{uuid}")
        return {"status": "success", "entries": [{"backend_uuid": uuid, "refetched": True}]}


def _write_discovery_ids(raw_dir: Path, uuids: list[str]) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    data = [
        {"uuid": u, "slug": f"slug-{u}", "title": "", "last_query_datetime": "", "mode": "", "query_count": 0, "is_pinned": False}
        for u in uuids
    ]
    (raw_dir / "discovery_ids.json").write_text(json.dumps(data), encoding="utf-8")


def _write_thread_file(raw_dir: Path, uuid: str, body: dict | None = None) -> None:
    thread_dir = raw_dir / "threads"
    thread_dir.mkdir(parents=True, exist_ok=True)
    (thread_dir / f"{uuid}.json").write_text(
        json.dumps(body or {"status": "old", "entries": [{"backend_uuid": uuid}]}),
        encoding="utf-8",
    )


# ============================================================
# _collect_known_uuids
# ============================================================

class TestCollectKnownUuids:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert _collect_known_uuids(tmp_path) == []

    def test_reads_discovery_ids(self, tmp_path):
        _write_discovery_ids(tmp_path, ["aaa", "bbb", "ccc"])
        assert _collect_known_uuids(tmp_path) == ["aaa", "bbb", "ccc"]

    def test_reads_threads_dir(self, tmp_path):
        _write_thread_file(tmp_path, "xxx")
        _write_thread_file(tmp_path, "yyy")
        result = _collect_known_uuids(tmp_path)
        assert set(result) == {"xxx", "yyy"}

    def test_unions_discovery_and_threads_dedup(self, tmp_path):
        """Thread fetchada que sumiu do listing fica no threads/, e thread
        descoberta-mas-nao-fetchada fica no discovery — uniao captura ambos."""
        _write_discovery_ids(tmp_path, ["aaa", "bbb"])
        _write_thread_file(tmp_path, "bbb")  # ja fetchada
        _write_thread_file(tmp_path, "ccc")  # sumiu do listing mas tem body
        result = _collect_known_uuids(tmp_path)
        assert set(result) == {"aaa", "bbb", "ccc"}
        # discovery_ids vem primeiro (ordem estavel)
        assert result.index("aaa") < result.index("ccc")

    def test_corrupt_discovery_skipped(self, tmp_path):
        (tmp_path).mkdir(parents=True, exist_ok=True)
        (tmp_path / "discovery_ids.json").write_text("not valid json {{{", encoding="utf-8")
        _write_thread_file(tmp_path, "zzz")
        assert _collect_known_uuids(tmp_path) == ["zzz"]


# ============================================================
# refetch_known_perplexity
# ============================================================

class TestRefetchKnownPerplexity:
    @pytest.mark.asyncio
    async def test_refetches_all_known_threads(self, tmp_path):
        _write_discovery_ids(tmp_path, ["uid1", "uid2", "uid3"])
        client = _FakeClient()

        stats = await refetch_known_perplexity(client, tmp_path, sleep_between=0)

        assert stats == {"total": 3, "updated": 3, "errors": 0}
        assert set(client.calls) == {"uid1", "uid2", "uid3"}
        # Cada thread foi sobrescrita com body fresco
        for uid in ("uid1", "uid2", "uid3"):
            body = json.loads((tmp_path / "threads" / f"{uid}.json").read_text())
            assert body["entries"][0]["refetched"] is True

    @pytest.mark.asyncio
    async def test_counts_errors_and_continues(self, tmp_path):
        _write_discovery_ids(tmp_path, ["ok1", "bad", "ok2"])
        client = _FakeClient(raise_for={"bad"})

        stats = await refetch_known_perplexity(client, tmp_path, sleep_between=0)

        assert stats == {"total": 3, "updated": 2, "errors": 1}
        # Os bons foram persistidos; o bad nao tem arquivo
        assert (tmp_path / "threads" / "ok1.json").exists()
        assert (tmp_path / "threads" / "ok2.json").exists()
        assert not (tmp_path / "threads" / "bad.json").exists()

    @pytest.mark.asyncio
    async def test_empty_state_returns_zero(self, tmp_path):
        """Sem discovery_ids e sem threads/ — nada a refetchar."""
        client = _FakeClient()
        stats = await refetch_known_perplexity(client, tmp_path, sleep_between=0)
        assert stats == {"total": 0, "updated": 0, "errors": 0}
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_includes_threads_only_in_threads_dir(self, tmp_path):
        """Thread que sumiu do listing mas tem body antigo no disco eh
        refetchada — preservation acima de tudo."""
        _write_discovery_ids(tmp_path, ["live"])
        _write_thread_file(tmp_path, "ghost")  # nao esta no discovery
        client = _FakeClient()

        stats = await refetch_known_perplexity(client, tmp_path, sleep_between=0)

        assert stats["total"] == 2
        assert stats["updated"] == 2
        assert set(client.calls) == {"live", "ghost"}
