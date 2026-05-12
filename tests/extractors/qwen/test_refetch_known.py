"""Testes do refetch_known fallback do Qwen.

Cobre:
- aux keys preserved (`_*` do arquivo anterior sobrevivem ao refetch)
- erros contados quando fetch_conversation levanta ou retorna success=False
- todos os IDs sao visitados
- conversations dir vazia/inexistente => zero counters
- _last_seen_in_server tagueado
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.extractors.qwen.refetch_known import refetch_known_qwen


class FakeClient:
    """Mock minimal de QwenAPIClient — implementa so fetch_conversation."""

    def __init__(
        self,
        *,
        raise_ids: set[str] | None = None,
        success_false_ids: set[str] | None = None,
    ):
        self.raise_ids = raise_ids or set()
        self.success_false_ids = success_false_ids or set()
        self.calls: list[str] = []

    async def fetch_conversation(self, conv_id: str) -> dict:
        self.calls.append(conv_id)
        if conv_id in self.raise_ids:
            raise RuntimeError(f"HTTP 500 on /v2/chats/{conv_id}")
        if conv_id in self.success_false_ids:
            return {"success": False, "request_id": "x", "data": {}}
        return {
            "success": True,
            "request_id": f"req-{conv_id}",
            "data": {
                "id": conv_id,
                "title": f"conv-{conv_id}-fresh",
                "updated_at": 1799999999,
            },
        }


def _write_conv(raw_dir: Path, cid: str, extra: dict | None = None) -> None:
    conv_dir = raw_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "success": True,
        "data": {"id": cid, "title": "old-title", "updated_at": 1700000000},
    }
    if extra:
        body.update(extra)
    (conv_dir / f"{cid}.json").write_text(json.dumps(body), encoding="utf-8")


class TestRefetchKnownQwen:
    def test_preserves_aux_keys(self, tmp_path):
        _write_conv(tmp_path, "c1", extra={
            "_last_seen_in_server": "2026-04-01",
            "_preserved_missing": False,
        })
        client = FakeClient()
        stats = asyncio.run(refetch_known_qwen(client, tmp_path, progress=False))
        assert stats["total"] == 1
        assert stats["updated"] == 1
        assert stats["errors"] == 0
        saved = json.loads((tmp_path / "conversations" / "c1.json").read_text())
        # Conteudo novo veio do fetch
        assert saved["data"]["title"] == "conv-c1-fresh"
        # Aux keys preservadas + _last_seen_in_server atualizado pra hoje
        assert saved["_preserved_missing"] is False
        # _last_seen_in_server sobrescrito pra hoje (sempre tag novo)
        assert "_last_seen_in_server" in saved
        # eh string YYYY-MM-DD
        assert len(saved["_last_seen_in_server"]) == 10

    def test_errors_counted_on_exception(self, tmp_path):
        _write_conv(tmp_path, "ok1")
        _write_conv(tmp_path, "bad1")
        _write_conv(tmp_path, "ok2")
        client = FakeClient(raise_ids={"bad1"})
        stats = asyncio.run(refetch_known_qwen(client, tmp_path, progress=False))
        assert stats["total"] == 3
        assert stats["updated"] == 2
        assert stats["errors"] == 1
        # bad1 fica intocado (mantem versao antiga)
        bad = json.loads((tmp_path / "conversations" / "bad1.json").read_text())
        assert bad["data"]["title"] == "old-title"

    def test_errors_counted_on_success_false(self, tmp_path):
        _write_conv(tmp_path, "c1")
        _write_conv(tmp_path, "c2")
        client = FakeClient(success_false_ids={"c2"})
        stats = asyncio.run(refetch_known_qwen(client, tmp_path, progress=False))
        assert stats["total"] == 2
        assert stats["updated"] == 1
        assert stats["errors"] == 1
        # c2 mantem versao antiga
        c2 = json.loads((tmp_path / "conversations" / "c2.json").read_text())
        assert c2["data"]["title"] == "old-title"

    def test_all_ids_visited(self, tmp_path):
        for cid in ["a", "b", "c", "d"]:
            _write_conv(tmp_path, cid)
        client = FakeClient()
        stats = asyncio.run(refetch_known_qwen(client, tmp_path, progress=False))
        assert stats["total"] == 4
        assert stats["updated"] == 4
        assert set(client.calls) == {"a", "b", "c", "d"}

    def test_empty_convs_dir_returns_zero(self, tmp_path):
        # tmp_path sem subpasta conversations/
        client = FakeClient()
        stats = asyncio.run(refetch_known_qwen(client, tmp_path, progress=False))
        assert stats == {"total": 0, "updated": 0, "errors": 0}
        assert client.calls == []

    def test_empty_convs_dir_existing_returns_zero(self, tmp_path):
        # conversations/ existe mas vazia
        (tmp_path / "conversations").mkdir()
        client = FakeClient()
        stats = asyncio.run(refetch_known_qwen(client, tmp_path, progress=False))
        assert stats == {"total": 0, "updated": 0, "errors": 0}
        assert client.calls == []

    def test_threshold_alias_still_exists(self):
        """Retro-compat: tests/code antigos podem referenciar o nome velho."""
        from src.extractors.qwen.orchestrator import (
            DISCOVERY_DROP_ABORT_THRESHOLD,
            DISCOVERY_DROP_FALLBACK_THRESHOLD,
        )
        assert DISCOVERY_DROP_ABORT_THRESHOLD == DISCOVERY_DROP_FALLBACK_THRESHOLD
        assert DISCOVERY_DROP_FALLBACK_THRESHOLD == 0.20
