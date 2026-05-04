# tests/test_unify_parquets.py
"""Testes pro scripts/unify-parquets.py.

Cobre os 5 helpers + fluxo end-to-end:
- `_identify_table` — sufixo simples e composto (source_guides vs sources)
- `_source_from_path` — extractor + manual + sufixo composto
- `discover_parquets` — varre dirs, ignora arquivos desconhecidos
- `unify_table` — concat, dedup PK composta, enriquece source ausente
- `unify` — fluxo completo, idempotência byte-a-byte

Bugs cobertos:
- PK composta `[source, conversation_id, message_id]` necessaria pra
  DeepSeek (message_id INT 1-98 local-por-conv) e Claude Code subagents
  (reusam parent's message_id em compactacao)
- UNION ALL BY NAME tolera schema divergente (capture_method ausente
  em parquets antigos)
- `project_metadata` nao tem coluna `source` no schema — enriquece via
  filename
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

# Carregar o script (nao eh modulo Python normal — fica em scripts/)
_unify_path = Path(__file__).parent.parent / "scripts" / "unify-parquets.py"
_spec = importlib.util.spec_from_file_location("unify_parquets", _unify_path)
unify_module = importlib.util.module_from_spec(_spec)
sys.modules["unify_parquets"] = unify_module
_spec.loader.exec_module(unify_module)


# === _identify_table ===


class TestIdentifyTable:
    def test_simple_suffix(self):
        assert unify_module._identify_table(Path("chatgpt_conversations.parquet")) == "conversations"
        assert unify_module._identify_table(Path("claude_ai_messages.parquet")) == "messages"

    def test_compound_suffix_source_guides_not_sources(self):
        """source_guides (13 chars) tem que matchar antes de sources (7 chars)
        senao 'notebooklm_source_guides.parquet' bateria com 'sources'."""
        assert unify_module._identify_table(Path("notebooklm_source_guides.parquet")) == "source_guides"
        assert unify_module._identify_table(Path("notebooklm_sources.parquet")) == "sources"

    def test_compound_suffix_guide_questions(self):
        assert unify_module._identify_table(Path("notebooklm_guide_questions.parquet")) == "guide_questions"

    def test_manual_suffix(self):
        assert unify_module._identify_table(Path("chatgpt_manual_messages.parquet")) == "messages"
        assert unify_module._identify_table(Path("notebooklm_manual_source_guides.parquet")) == "source_guides"

    def test_unknown_returns_none(self):
        assert unify_module._identify_table(Path("chatgpt_random_thing.parquet")) is None
        assert unify_module._identify_table(Path("foo.parquet")) is None


# === _source_from_path ===


class TestSourceFromPath:
    def test_simple(self):
        assert unify_module._source_from_path(Path("qwen_project_metadata.parquet")) == "qwen"
        assert unify_module._source_from_path(Path("chatgpt_conversations.parquet")) == "chatgpt"

    def test_compound_source_name(self):
        # claude_ai tem underscore — nao confundir com sufixo de table
        assert unify_module._source_from_path(Path("claude_ai_messages.parquet")) == "claude_ai"

    def test_manual_strips_correctly(self):
        assert unify_module._source_from_path(Path("chatgpt_manual_messages.parquet")) == "chatgpt"
        assert unify_module._source_from_path(Path("claude_ai_manual_branches.parquet")) == "claude_ai"

    def test_unknown_returns_empty(self):
        assert unify_module._source_from_path(Path("random_file.parquet")) == ""


# === Fixture compartilhado ===


@pytest.fixture
def fake_processed(tmp_path):
    """Layout fake `data/processed/<Plat>/<source>_<table>.parquet` com 2 sources."""
    processed = tmp_path / "processed"
    processed.mkdir()

    # Fake Plataforma A (source 'sourceA')
    a_dir = processed / "PlataformaA"
    a_dir.mkdir()
    pd.DataFrame({
        "conversation_id": ["c1", "c2"],
        "source": ["sourceA"] * 2,
        "title": ["A1", "A2"],
        "message_count": [3, 5],
    }).to_parquet(a_dir / "sourceA_conversations.parquet")

    # Tem manual saves tambem (com capture_method extra)
    pd.DataFrame({
        "conversation_id": ["c3"],
        "source": ["sourceA"],
        "title": ["A3 manual"],
        "message_count": [1],
        "capture_method": ["manual_clipping_obsidian"],
    }).to_parquet(a_dir / "sourceA_manual_conversations.parquet")

    # Messages com PK local-por-conv (simulando bug DeepSeek)
    pd.DataFrame({
        "message_id": ["1", "2", "1", "2", "3"],  # IDs colidem entre convs!
        "conversation_id": ["c1", "c1", "c2", "c2", "c2"],
        "source": ["sourceA"] * 5,
        "role": ["user", "assistant"] * 2 + ["user"],
    }).to_parquet(a_dir / "sourceA_messages.parquet")

    # Fake Plataforma B (source 'sourceB')
    b_dir = processed / "PlataformaB"
    b_dir.mkdir()
    pd.DataFrame({
        "conversation_id": ["d1"],
        "source": ["sourceB"],
        "title": ["B1"],
        "message_count": [2],
    }).to_parquet(b_dir / "sourceB_conversations.parquet")

    # project_metadata SEM coluna source (vai enriquecer no unify)
    pd.DataFrame({
        "project_id": ["p1", "p2"],
        "name": ["proj1", "proj2"],
    }).to_parquet(b_dir / "sourceB_project_metadata.parquet")

    return processed


# === discover_parquets ===


class TestDiscoverParquets:
    def test_discovers_all_known_tables(self, fake_processed):
        result = unify_module.discover_parquets(fake_processed)
        # Deve ter conversations (3 arquivos: A ext, A manual, B), messages (1: A), project_metadata (1: B)
        assert len(result["conversations"]) == 3
        assert len(result["messages"]) == 1
        assert len(result["project_metadata"]) == 1
        # Tabelas sem parquets ficam com lista vazia
        assert result["branches"] == []

    def test_ignores_unknown_files(self, fake_processed, caplog):
        # Adicionar arquivo desconhecido
        (fake_processed / "PlataformaA" / "sourceA_unknown.parquet").write_bytes(b"")
        result = unify_module.discover_parquets(fake_processed)
        # Nao adiciona ao result; warning emitido (nao validamos exatamente, so passa sem crashar)
        assert "unknown" not in result


# === unify_table ===


class TestUnifyTable:
    def test_concat_extractor_plus_manual(self, fake_processed):
        result = unify_module.discover_parquets(fake_processed)
        df = unify_module.unify_table("conversations", result["conversations"])
        # 2 (A ext) + 1 (A manual) + 1 (B) = 4
        assert len(df) == 4
        # capture_method existe (vem do manual A); NULL pros outros
        assert "capture_method" in df.columns
        n_with_cm = df["capture_method"].notna().sum()
        assert n_with_cm == 1

    def test_dedup_pk_includes_conv_id(self, fake_processed):
        """PK composta evita colapsar IDs locais por conv (bug DeepSeek)."""
        result = unify_module.discover_parquets(fake_processed)
        df = unify_module.unify_table("messages", result["messages"])
        # 5 messages, todos unicos pela PK [source, conv_id, msg_id]
        # (mesmo que message_id="1" e "2" se repitam entre c1 e c2)
        assert len(df) == 5

    def test_enriches_source_when_absent(self, fake_processed):
        """project_metadata nao tem coluna source no schema — enriquecer via filename."""
        result = unify_module.discover_parquets(fake_processed)
        df = unify_module.unify_table("project_metadata", result["project_metadata"])
        assert "source" in df.columns
        assert df["source"].iloc[0] == "sourceB"
        assert len(df) == 2

    def test_dedup_keep_last(self, tmp_path):
        """Quando ha colisao real (PK identica), keep='last' favorece o ultimo file."""
        d = tmp_path / "PlatX"
        d.mkdir()
        # 2 arquivos com MESMA PK pra mesma row
        pd.DataFrame({
            "conversation_id": ["c1"], "source": ["x"], "title": ["v1 (extractor)"],
        }).to_parquet(d / "x_conversations.parquet")
        pd.DataFrame({
            "conversation_id": ["c1"], "source": ["x"], "title": ["v2 (manual)"],
            "capture_method": ["manual_clipping_obsidian"],
        }).to_parquet(d / "x_manual_conversations.parquet")

        files = sorted(d.glob("*.parquet"))  # alfabetico: x_conv... antes de x_manual_conv
        df = unify_module.unify_table("conversations", files)
        assert len(df) == 1
        # keep='last' favorece o que vem depois alfabeticamente (manual)
        assert df["title"].iloc[0] == "v2 (manual)"


# === unify (end-to-end) ===


class TestUnifyEndToEnd:
    def test_writes_all_tables_to_unified_dir(self, fake_processed, tmp_path):
        unified = tmp_path / "unified"
        counts = unify_module.unify(fake_processed, unified)
        # 3 tabelas com dados nesse fixture
        assert "conversations" in counts and counts["conversations"] == 4
        assert "messages" in counts and counts["messages"] == 5
        assert "project_metadata" in counts and counts["project_metadata"] == 2
        # Arquivos escritos
        assert (unified / "conversations.parquet").exists()
        assert (unified / "messages.parquet").exists()
        assert (unified / "project_metadata.parquet").exists()
        # Tabelas vazias nao foram escritas
        assert not (unified / "branches.parquet").exists()

    def test_idempotent(self, fake_processed, tmp_path):
        """Rodar 2x produz arquivos byte-a-byte identicos."""
        unified = tmp_path / "unified"
        unify_module.unify(fake_processed, unified)
        snapshot = {
            f.name: f.read_bytes()
            for f in unified.glob("*.parquet")
        }
        unify_module.unify(fake_processed, unified)
        for f in unified.glob("*.parquet"):
            assert f.read_bytes() == snapshot[f.name], f"{f.name} mudou na 2a run"

    def test_preserves_source_column(self, fake_processed, tmp_path):
        """Coluna source deve estar presente em todos os parquets escritos
        (incluindo project_metadata enriquecido)."""
        unified = tmp_path / "unified"
        unify_module.unify(fake_processed, unified)
        for f in unified.glob("*.parquet"):
            df = pd.read_parquet(f)
            assert "source" in df.columns, f"{f.name} sem coluna source"
