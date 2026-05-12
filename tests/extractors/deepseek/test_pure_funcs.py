"""Smoke tests pra funções puras do extractor DeepSeek."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.extractors.deepseek.asset_downloader import _collect_files
from src.extractors.deepseek.orchestrator import (
    DISCOVERY_DROP_ABORT_THRESHOLD,
    DISCOVERY_DROP_FALLBACK_THRESHOLD,
    _get_max_known_discovery,
)
from src.extractors.deepseek.refetch_known import refetch_known_deepseek


class TestCollectFiles:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert _collect_files(tmp_path) == []

    def test_collects_files_from_messages(self, tmp_path):
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()
        (conv_dir / "c1.json").write_text(json.dumps({
            "chat_session": {"id": "c1"},
            "chat_messages": [
                {
                    "message_id": "m1",
                    "files": [
                        {"id": "f1", "name": "doc.pdf", "size": 1024},
                        {"id": "f2", "name": "img.png", "size": 2048},
                    ],
                },
            ],
        }), encoding="utf-8")

        result = _collect_files(tmp_path)
        ids = {r["file_id"] for r in result}
        assert ids == {"f1", "f2"}
        # Cada entry tem conv_id e message_id
        assert all(r.get("conv_id") == "c1" for r in result)

    def test_skips_files_without_id(self, tmp_path):
        """File sem `id` é ignorado defensivamente."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()
        (conv_dir / "c1.json").write_text(json.dumps({
            "chat_session": {"id": "c1"},
            "chat_messages": [
                {
                    "message_id": "m1",
                    "files": [
                        {"id": "f1", "name": "ok.pdf"},
                        {"name": "no-id.pdf"},  # sem id — deve ser pulado
                    ],
                },
            ],
        }), encoding="utf-8")

        result = _collect_files(tmp_path)
        assert len(result) == 1
        assert result[0]["file_id"] == "f1"


class TestGetMaxKnownDiscovery:
    def test_no_dir_returns_zero(self, tmp_path):
        assert _get_max_known_discovery(tmp_path / "ghost") == 0

    def test_reads_max(self, tmp_path):
        log = tmp_path / "capture_log.jsonl"
        log.write_text("\n".join([
            json.dumps({"totals": {"conversations_discovered": 30}}),
            json.dumps({"totals": {"conversations_discovered": 75}}),
        ]) + "\n", encoding="utf-8")
        assert _get_max_known_discovery(tmp_path) == 75


class TestRefetchKnownDeepSeek:
    def test_threshold_alias_retrocompat(self):
        """O nome antigo continua valendo, sem divergencia."""
        assert DISCOVERY_DROP_ABORT_THRESHOLD == DISCOVERY_DROP_FALLBACK_THRESHOLD

    def test_missing_dir_raises(self, tmp_path):
        class FakeClient:
            async def fetch_conversation(self, cid):
                return {}

        with pytest.raises(FileNotFoundError):
            asyncio.run(refetch_known_deepseek(FakeClient(), tmp_path))

    def test_refetches_all_preserves_aux(self, tmp_path):
        """Refetcha cada conv, preserva chaves `_*` e sobrescreve in-place."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()
        (conv_dir / "c1.json").write_text(json.dumps({
            "chat_session": {"id": "c1", "title": "old"},
            "chat_messages": [],
            "_last_seen_in_server": "2025-01-01",
        }), encoding="utf-8")
        (conv_dir / "c2.json").write_text(json.dumps({
            "chat_session": {"id": "c2", "title": "old2"},
            "chat_messages": [],
            "_last_seen_in_server": "2025-01-02",
        }), encoding="utf-8")

        calls: list[str] = []

        class FakeClient:
            async def fetch_conversation(self, cid):
                calls.append(cid)
                return {
                    "chat_session": {"id": cid, "title": f"new-{cid}"},
                    "chat_messages": [{"message_id": "m1"}],
                }

        stats = asyncio.run(refetch_known_deepseek(FakeClient(), tmp_path, progress=False))

        assert stats == {"total": 2, "updated": 2, "errors": 0}
        assert sorted(calls) == ["c1", "c2"]
        # Aux preservada + payload novo gravado
        c1 = json.loads((conv_dir / "c1.json").read_text(encoding="utf-8"))
        assert c1["chat_session"]["title"] == "new-c1"
        assert c1["_last_seen_in_server"] == "2025-01-01"
        assert c1["chat_messages"] == [{"message_id": "m1"}]
        c2 = json.loads((conv_dir / "c2.json").read_text(encoding="utf-8"))
        assert c2["_last_seen_in_server"] == "2025-01-02"

    def test_errors_dont_abort(self, tmp_path):
        """Falha em uma conv conta erro mas nao mata a iteracao."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()
        (conv_dir / "c1.json").write_text(json.dumps({"chat_session": {"id": "c1"}}), encoding="utf-8")
        (conv_dir / "c2.json").write_text(json.dumps({"chat_session": {"id": "c2"}}), encoding="utf-8")

        class FakeClient:
            async def fetch_conversation(self, cid):
                if cid == "c1":
                    raise RuntimeError("HTTP 500")
                return {"chat_session": {"id": cid, "title": "ok"}}

        stats = asyncio.run(refetch_known_deepseek(FakeClient(), tmp_path, progress=False))

        assert stats == {"total": 2, "updated": 1, "errors": 1}
        # c2 foi atualizado
        c2 = json.loads((conv_dir / "c2.json").read_text(encoding="utf-8"))
        assert c2["chat_session"]["title"] == "ok"
