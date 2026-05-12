"""Tests pra refetch_known_gemini — fallback quando discovery (MaZiqc) parcial.

Mocka `GeminiAPIClient.fetch_conversation`. Cobre:
- happy path: todos os UUIDs do discovery_ids sao refetchados e salvos
- preservacao de chaves auxiliares `_*` em arquivos existentes
- erros individuais (fetch retornando None / exception) contam pra `errors`
- ausencia de discovery_ids.json levanta FileNotFoundError
- multi-account: cada account_dir eh tratado isoladamente
- threshold alias (DISCOVERY_DROP_ABORT_THRESHOLD == FALLBACK_THRESHOLD)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.extractors.gemini.refetch_known import refetch_known_gemini
from src.extractors.gemini import orchestrator


def _write_discovery(account_dir: Path, uuids: list[str]) -> None:
    account_dir.mkdir(parents=True, exist_ok=True)
    payload = [
        {"uuid": u, "title": f"t-{u}", "pinned": False, "created_at_secs": 1700000000 + i}
        for i, u in enumerate(uuids)
    ]
    (account_dir / "discovery_ids.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_threshold_alias_retro_compat():
    """Nome antigo continua exportado (testes/codigo antigo nao quebra)."""
    assert (
        orchestrator.DISCOVERY_DROP_ABORT_THRESHOLD
        == orchestrator.DISCOVERY_DROP_FALLBACK_THRESHOLD
        == 0.20
    )


def test_no_discovery_file_raises(tmp_path):
    client = AsyncMock()
    with pytest.raises(FileNotFoundError):
        asyncio.run(refetch_known_gemini(client, tmp_path))


def test_refetches_all_known_uuids(tmp_path):
    uuids = ["c_aaa", "c_bbb", "c_ccc"]
    _write_discovery(tmp_path, uuids)

    client = AsyncMock()

    async def _fake_fetch(uuid: str):
        return {"uuid": uuid, "raw": [["fake-body-for", uuid]]}

    client.fetch_conversation = AsyncMock(side_effect=_fake_fetch)

    stats = asyncio.run(refetch_known_gemini(client, tmp_path))

    assert stats == {"total": 3, "updated": 3, "errors": 0}
    assert client.fetch_conversation.await_count == 3
    for u in uuids:
        body = json.loads((tmp_path / "conversations" / f"{u}.json").read_text())
        assert body["uuid"] == u
        assert "_last_seen_in_server" in body  # tag aplicada
        assert body["raw"] == [["fake-body-for", u]]


def test_preserves_aux_keys_on_existing_files(tmp_path):
    """Chaves `_*` em arquivos existentes nao podem ser pisadas pelo refetch."""
    uuid = "c_keep_aux"
    _write_discovery(tmp_path, [uuid])

    conv_dir = tmp_path / "conversations"
    conv_dir.mkdir()
    existing = {
        "uuid": uuid,
        "raw": [["old-stale-body"]],
        "_last_seen_in_server": "2026-01-01",
        "_custom_aux": "preserve-me",
    }
    (conv_dir / f"{uuid}.json").write_text(json.dumps(existing), encoding="utf-8")

    client = AsyncMock()
    # Note: o fetch NAO retorna `_custom_aux` — refetch precisa restaurar
    client.fetch_conversation = AsyncMock(
        return_value={"uuid": uuid, "raw": [["new-fresh-body"]]}
    )

    stats = asyncio.run(refetch_known_gemini(client, tmp_path))
    assert stats["updated"] == 1

    body = json.loads((conv_dir / f"{uuid}.json").read_text())
    assert body["raw"] == [["new-fresh-body"]]  # raw foi atualizado
    assert body["_custom_aux"] == "preserve-me"  # aux preservado
    # _last_seen_in_server foi bumped pra hoje (nao o valor antigo)
    assert body["_last_seen_in_server"] != "2026-01-01"


def test_counts_errors_on_none_return(tmp_path):
    uuids = ["c_ok", "c_none", "c_ok2"]
    _write_discovery(tmp_path, uuids)

    client = AsyncMock()

    async def _fake_fetch(uuid: str):
        if uuid == "c_none":
            return None
        return {"uuid": uuid, "raw": []}

    client.fetch_conversation = AsyncMock(side_effect=_fake_fetch)

    stats = asyncio.run(refetch_known_gemini(client, tmp_path))
    assert stats == {"total": 3, "updated": 2, "errors": 1}
    # Arquivo c_none NAO foi escrito
    assert not (tmp_path / "conversations" / "c_none.json").exists()


def test_counts_errors_on_exception(tmp_path):
    uuids = ["c_ok", "c_boom"]
    _write_discovery(tmp_path, uuids)

    client = AsyncMock()

    async def _fake_fetch(uuid: str):
        if uuid == "c_boom":
            raise RuntimeError("simulated network error")
        return {"uuid": uuid, "raw": []}

    client.fetch_conversation = AsyncMock(side_effect=_fake_fetch)

    stats = asyncio.run(refetch_known_gemini(client, tmp_path))
    assert stats == {"total": 2, "updated": 1, "errors": 1}


def test_multi_account_isolation(tmp_path):
    """account-1 e account-2 sao pastas separadas; refetch eh per-account."""
    acc1 = tmp_path / "account-1"
    acc2 = tmp_path / "account-2"
    _write_discovery(acc1, ["c_acc1_a", "c_acc1_b"])
    _write_discovery(acc2, ["c_acc2_x"])

    client = AsyncMock()
    client.fetch_conversation = AsyncMock(
        side_effect=lambda u: {"uuid": u, "raw": []}
    )

    s1 = asyncio.run(refetch_known_gemini(client, acc1))
    s2 = asyncio.run(refetch_known_gemini(client, acc2))

    assert s1 == {"total": 2, "updated": 2, "errors": 0}
    assert s2 == {"total": 1, "updated": 1, "errors": 0}
    # Arquivos foram pra pastas corretas — sem cross-contamination
    assert (acc1 / "conversations" / "c_acc1_a.json").exists()
    assert (acc1 / "conversations" / "c_acc1_b.json").exists()
    assert (acc2 / "conversations" / "c_acc2_x.json").exists()
    assert not (acc1 / "conversations" / "c_acc2_x.json").exists()
    assert not (acc2 / "conversations" / "c_acc1_a.json").exists()


def test_corrupted_discovery_file_raises(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "discovery_ids.json").write_text("{not valid json", encoding="utf-8")
    client = AsyncMock()
    with pytest.raises(RuntimeError, match="corrompido"):
        asyncio.run(refetch_known_gemini(client, tmp_path))


def test_skips_entries_without_uuid(tmp_path):
    """discovery_ids.json com entradas malformadas (sem uuid) sao ignoradas."""
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "discovery_ids.json").write_text(
        json.dumps([
            {"uuid": "c_valid", "title": "ok"},
            {"title": "sem-uuid"},
            {"uuid": None},
            {"uuid": "c_other"},
        ]),
        encoding="utf-8",
    )
    client = AsyncMock()
    client.fetch_conversation = AsyncMock(
        side_effect=lambda u: {"uuid": u, "raw": []}
    )

    stats = asyncio.run(refetch_known_gemini(client, tmp_path))
    assert stats["total"] == 2  # so c_valid e c_other contam
    assert stats["updated"] == 2
