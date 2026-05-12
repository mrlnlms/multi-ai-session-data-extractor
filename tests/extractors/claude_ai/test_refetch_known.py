"""Testes do refetch_known fallback do Claude.ai.

Cobre:
- aux keys preserved (`_*` do arquivo anterior sobrevivem ao refetch)
- erros contados quando fetch_conversation levanta
- todos os IDs sao visitados
- collect prefere conversations/*.json, fallback discovery_ids.json
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.extractors.claude_ai.refetch_known import (
    _collect_known_ids,
    refetch_known_claude_ai,
)


class FakeClient:
    """Mock minimal de ClaudeAPIClient — implementa so fetch_conversation."""

    def __init__(self, *, fail_ids: set[str] | None = None, fail_always: set[str] | None = None):
        self.fail_ids = fail_ids or set()  # falha 1x depois passa (testa retry)
        self.fail_always = fail_always or set()  # sempre falha
        self.calls: list[str] = []
        self._attempts: dict[str, int] = {}

    async def fetch_conversation(self, uuid: str) -> dict:
        self.calls.append(uuid)
        n = self._attempts.get(uuid, 0)
        self._attempts[uuid] = n + 1
        if uuid in self.fail_always:
            raise RuntimeError(f"sempre falha {uuid}")
        if uuid in self.fail_ids and n == 0:
            raise RuntimeError(f"flake transiente {uuid}")
        return {
            "uuid": uuid,
            "name": f"conv-{uuid}",
            "chat_messages": [{"role": "user", "text": "hi"}],
        }


def _write_conv(raw_dir: Path, uid: str, extra: dict | None = None) -> None:
    conv_dir = raw_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    body = {"uuid": uid, "name": "old-name", "chat_messages": []}
    if extra:
        body.update(extra)
    (conv_dir / f"{uid}.json").write_text(json.dumps(body), encoding="utf-8")


class TestCollectKnownIds:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert _collect_known_ids(tmp_path) == []

    def test_reads_from_conversations_dir(self, tmp_path):
        _write_conv(tmp_path, "uuid-a")
        _write_conv(tmp_path, "uuid-b")
        ids = _collect_known_ids(tmp_path)
        assert set(ids) == {"uuid-a", "uuid-b"}

    def test_falls_back_to_discovery_when_no_convs(self, tmp_path):
        disc = tmp_path / "discovery_ids.json"
        disc.write_text(json.dumps({
            "conversations": [{"uuid": "x1"}, {"uuid": "x2"}, {"uuid": "x3"}],
        }), encoding="utf-8")
        ids = _collect_known_ids(tmp_path)
        assert set(ids) == {"x1", "x2", "x3"}

    def test_prefers_convs_dir_over_discovery(self, tmp_path):
        _write_conv(tmp_path, "from-disk")
        disc = tmp_path / "discovery_ids.json"
        disc.write_text(json.dumps({
            "conversations": [{"uuid": "from-discovery"}],
        }), encoding="utf-8")
        ids = _collect_known_ids(tmp_path)
        assert ids == ["from-disk"]


class TestRefetchKnownClaudeAi:
    def test_preserves_aux_keys(self, tmp_path):
        _write_conv(tmp_path, "u1", extra={
            "_last_seen_in_server": "2026-04-01",
            "_preserved_missing": False,
        })
        client = FakeClient()
        stats = asyncio.run(
            refetch_known_claude_ai(client, tmp_path, retries=0, backoff_base=0.0)
        )
        assert stats == {"total": 1, "updated": 1, "errors": 0}
        saved = json.loads((tmp_path / "conversations" / "u1.json").read_text())
        # Conteudo novo veio do fetch
        assert saved["name"] == "conv-u1"
        # Aux keys preservadas
        assert saved["_last_seen_in_server"] == "2026-04-01"
        assert saved["_preserved_missing"] is False

    def test_errors_counted(self, tmp_path):
        _write_conv(tmp_path, "ok1")
        _write_conv(tmp_path, "bad1")
        _write_conv(tmp_path, "ok2")
        client = FakeClient(fail_always={"bad1"})
        stats = asyncio.run(
            refetch_known_claude_ai(client, tmp_path, retries=0, backoff_base=0.0)
        )
        assert stats["total"] == 3
        assert stats["updated"] == 2
        assert stats["errors"] == 1
        # Arquivo do bad1 fica intocado (mantem versao antiga)
        bad = json.loads((tmp_path / "conversations" / "bad1.json").read_text())
        assert bad["name"] == "old-name"

    def test_all_ids_visited(self, tmp_path):
        for uid in ["a", "b", "c", "d"]:
            _write_conv(tmp_path, uid)
        client = FakeClient()
        stats = asyncio.run(
            refetch_known_claude_ai(client, tmp_path, retries=0, backoff_base=0.0)
        )
        assert stats["total"] == 4
        assert set(client.calls) == {"a", "b", "c", "d"}

    def test_retry_on_transient_error(self, tmp_path):
        _write_conv(tmp_path, "flake")
        client = FakeClient(fail_ids={"flake"})  # falha 1x depois passa
        stats = asyncio.run(
            refetch_known_claude_ai(client, tmp_path, retries=2, backoff_base=0.0)
        )
        assert stats == {"total": 1, "updated": 1, "errors": 0}
        # 2 tentativas: 1 falha + 1 sucesso
        assert client.calls.count("flake") == 2

    def test_empty_raw_returns_zero(self, tmp_path):
        client = FakeClient()
        stats = asyncio.run(
            refetch_known_claude_ai(client, tmp_path, retries=0, backoff_base=0.0)
        )
        assert stats == {"total": 0, "updated": 0, "errors": 0}
        assert client.calls == []
