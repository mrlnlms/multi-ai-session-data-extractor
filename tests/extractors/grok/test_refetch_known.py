"""Testes pro fallback de discovery-drop em Grok (refetch_known_grok)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.extractors.grok.refetch_known import (
    _load_known_conv_ids,
    refetch_known_grok,
)
from src.extractors.grok.orchestrator import (
    DISCOVERY_DROP_ABORT_THRESHOLD,
    DISCOVERY_DROP_FALLBACK_THRESHOLD,
)


class FakeClient:
    """Mock do GrokAPIClient — so precisa de fetch_full_conversation."""

    def __init__(self, fail_ids: set[str] | None = None):
        self.fail_ids = fail_ids or set()
        self.calls: list[str] = []

    async def fetch_full_conversation(self, conv_id: str) -> dict:
        self.calls.append(conv_id)
        if conv_id in self.fail_ids:
            raise RuntimeError(f"forced failure for {conv_id}")
        return {
            "conversation_v2": {"conversation": {"conversationId": conv_id, "title": f"t-{conv_id}"}},
            "response_node": {"responseNodes": []},
            "responses": {"responses": []},
            "files": {"files": []},
            "share_links": {"shareLinks": []},
        }


def _write_discovery(raw_dir: Path, ids: list[str]) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    disc = [
        {"conversationId": cid, "title": f"t-{cid}", "modifyTime": "2026-05-09T00:00:00Z"}
        for cid in ids
    ]
    (raw_dir / "discovery_ids.json").write_text(json.dumps(disc, ensure_ascii=False), encoding="utf-8")


def _write_existing_conv(raw_dir: Path, cid: str, aux: dict | None = None) -> None:
    conv_dir = raw_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "conversation_v2": {"conversation": {"conversationId": cid, "title": "OLD"}},
        "response_node": {"responseNodes": []},
        "responses": {"responses": []},
        "files": {"files": []},
        "share_links": {"shareLinks": []},
    }
    if aux:
        payload.update(aux)
    (conv_dir / f"{cid}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_threshold_alias_retro_compat():
    """Alias velho aponta pro mesmo valor que o nome novo."""
    assert DISCOVERY_DROP_ABORT_THRESHOLD == DISCOVERY_DROP_FALLBACK_THRESHOLD == 0.20


def test_load_known_conv_ids_prefers_discovery(tmp_path: Path):
    _write_discovery(tmp_path, ["a", "b", "c"])
    assert _load_known_conv_ids(tmp_path) == ["a", "b", "c"]


def test_load_known_conv_ids_falls_back_to_conversations_dir(tmp_path: Path):
    # Sem discovery_ids.json, le do filesystem
    _write_existing_conv(tmp_path, "z1")
    _write_existing_conv(tmp_path, "z2")
    ids = _load_known_conv_ids(tmp_path)
    assert sorted(ids) == ["z1", "z2"]


def test_load_known_conv_ids_empty_when_no_data(tmp_path: Path):
    assert _load_known_conv_ids(tmp_path) == []


def test_refetch_known_grok_rewrites_all_convs(tmp_path: Path):
    """Refetch sobrescreve in-place e retorna counts corretos."""
    _write_discovery(tmp_path, ["a", "b"])
    _write_existing_conv(tmp_path, "a")
    _write_existing_conv(tmp_path, "b")

    client = FakeClient()
    stats = asyncio.run(refetch_known_grok(client, tmp_path, progress=False))

    assert stats == {"total": 2, "updated": 2, "errors": 0}
    assert sorted(client.calls) == ["a", "b"]
    # Verifica que o conteudo foi reescrito (title agora != "OLD")
    for cid in ("a", "b"):
        data = json.loads((tmp_path / "conversations" / f"{cid}.json").read_text())
        assert data["conversation_v2"]["conversation"]["title"] == f"t-{cid}"


def test_refetch_known_grok_preserves_aux_keys(tmp_path: Path):
    """Chaves `_*` (ex: _last_seen_in_server) do arquivo antigo sao preservadas."""
    _write_discovery(tmp_path, ["x"])
    _write_existing_conv(tmp_path, "x", aux={"_last_seen_in_server": "2026-04-01", "_custom": 42})

    client = FakeClient()
    stats = asyncio.run(refetch_known_grok(client, tmp_path, progress=False))

    assert stats["updated"] == 1
    data = json.loads((tmp_path / "conversations" / "x.json").read_text())
    assert data["_last_seen_in_server"] == "2026-04-01"
    assert data["_custom"] == 42
    # E o conteudo novo veio do fetch
    assert data["conversation_v2"]["conversation"]["title"] == "t-x"


def test_refetch_known_grok_counts_errors(tmp_path: Path):
    """Failures sao contadas em `errors`, nao quebram o loop."""
    _write_discovery(tmp_path, ["ok1", "bad", "ok2"])

    client = FakeClient(fail_ids={"bad"})
    stats = asyncio.run(refetch_known_grok(client, tmp_path, progress=False))

    assert stats == {"total": 3, "updated": 2, "errors": 1}
    # Convs OK foram escritas
    assert (tmp_path / "conversations" / "ok1.json").exists()
    assert (tmp_path / "conversations" / "ok2.json").exists()
    # Conv que falhou nao tem arquivo (e nao foi forcada criacao)
    assert not (tmp_path / "conversations" / "bad.json").exists()


def test_refetch_known_grok_raises_when_no_known_ids(tmp_path: Path):
    """Sem discovery_ids.json e sem conversations/, levanta FileNotFoundError."""
    client = FakeClient()
    with pytest.raises(FileNotFoundError):
        asyncio.run(refetch_known_grok(client, tmp_path, progress=False))


def test_refetch_known_grok_uses_conversations_dir_when_no_discovery(tmp_path: Path):
    """Sem discovery_ids.json, usa filenames de conversations/ como fonte de IDs."""
    _write_existing_conv(tmp_path, "fromdir1")
    _write_existing_conv(tmp_path, "fromdir2")
    client = FakeClient()
    stats = asyncio.run(refetch_known_grok(client, tmp_path, progress=False))

    assert stats == {"total": 2, "updated": 2, "errors": 0}
    assert sorted(client.calls) == ["fromdir1", "fromdir2"]
