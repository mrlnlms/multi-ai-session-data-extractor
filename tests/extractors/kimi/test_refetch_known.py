"""Testes do refetch_known fallback do Kimi.

Cobre:
- aux keys preservadas (`_*` do arquivo anterior sobrevivem ao refetch)
- erros contados quando fetch_full_chat levanta
- todos os IDs sao visitados
- raw vazio retorna zeros
- _last_seen_in_server marcado com a data de hoje
- FileNotFoundError quando conversations dir nao existe
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.extractors.kimi.refetch_known import refetch_known_kimi


class FakeKimiClient:
    """Mock minimal de KimiAPIClient — implementa so fetch_full_chat."""

    def __init__(self, *, fail_always: set[str] | None = None):
        self.fail_always = fail_always or set()
        self.calls: list[str] = []

    async def fetch_full_chat(self, chat_id: str) -> dict:
        self.calls.append(chat_id)
        if chat_id in self.fail_always:
            raise RuntimeError(f"sempre falha {chat_id}")
        return {
            "chat": {"id": chat_id, "name": f"chat-{chat_id}", "updateTime": "2026-05-12T00:00:00Z"},
            "messages": [{"role": "user", "content": "hi"}],
        }


def _write_conv(raw_dir: Path, cid: str, extra: dict | None = None) -> None:
    conv_dir = raw_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    body = {"chat": {"id": cid, "name": "old-name"}, "messages": []}
    if extra:
        body.update(extra)
    (conv_dir / f"{cid}.json").write_text(json.dumps(body), encoding="utf-8")


class TestRefetchKnownKimi:
    def test_preserves_aux_keys(self, tmp_path):
        _write_conv(tmp_path, "u1", extra={
            "_last_seen_in_server": "2026-04-01",
            "_preserved_missing": False,
        })
        client = FakeKimiClient()
        stats = asyncio.run(refetch_known_kimi(client, tmp_path, progress=False))
        assert stats["total"] == 1
        assert stats["updated"] == 1
        assert stats["errors"] == 0
        saved = json.loads((tmp_path / "conversations" / "u1.json").read_text())
        # Conteudo novo veio do fetch
        assert saved["chat"]["name"] == "chat-u1"
        # Aux _preserved_missing key preservada
        assert saved["_preserved_missing"] is False
        # _last_seen_in_server eh sobrescrito com hoje (nao o valor antigo)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert saved["_last_seen_in_server"] == today

    def test_errors_counted(self, tmp_path):
        _write_conv(tmp_path, "ok1")
        _write_conv(tmp_path, "bad1")
        _write_conv(tmp_path, "ok2")
        client = FakeKimiClient(fail_always={"bad1"})
        stats = asyncio.run(refetch_known_kimi(client, tmp_path, progress=False))
        assert stats["total"] == 3
        assert stats["updated"] == 2
        assert stats["errors"] == 1
        # Arquivo do bad1 fica intocado (mantem versao antiga)
        bad = json.loads((tmp_path / "conversations" / "bad1.json").read_text())
        assert bad["chat"]["name"] == "old-name"

    def test_all_ids_visited(self, tmp_path):
        for cid in ["a", "b", "c", "d"]:
            _write_conv(tmp_path, cid)
        client = FakeKimiClient()
        stats = asyncio.run(refetch_known_kimi(client, tmp_path, progress=False))
        assert stats["total"] == 4
        assert set(client.calls) == {"a", "b", "c", "d"}

    def test_empty_raw_returns_zero(self, tmp_path):
        # conversations/ existe mas vazio
        (tmp_path / "conversations").mkdir(parents=True)
        client = FakeKimiClient()
        stats = asyncio.run(refetch_known_kimi(client, tmp_path, progress=False))
        assert stats == {"total": 0, "updated": 0, "errors": 0}
        assert client.calls == []

    def test_missing_conv_dir_raises(self, tmp_path):
        client = FakeKimiClient()
        with pytest.raises(FileNotFoundError):
            asyncio.run(refetch_known_kimi(client, tmp_path, progress=False))

    def test_marks_last_seen_in_server(self, tmp_path):
        _write_conv(tmp_path, "x1")
        client = FakeKimiClient()
        asyncio.run(refetch_known_kimi(client, tmp_path, progress=False))
        saved = json.loads((tmp_path / "conversations" / "x1.json").read_text())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert saved["_last_seen_in_server"] == today

    def test_non_dict_response_counted_as_error(self, tmp_path):
        _write_conv(tmp_path, "weird")

        class WeirdClient:
            calls: list[str] = []

            async def fetch_full_chat(self, cid: str):
                self.calls.append(cid)
                return ["not", "a", "dict"]

        client = WeirdClient()
        stats = asyncio.run(refetch_known_kimi(client, tmp_path, progress=False))
        assert stats["total"] == 1
        assert stats["updated"] == 0
        assert stats["errors"] == 1
