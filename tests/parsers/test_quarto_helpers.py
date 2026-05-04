# tests/parsers/test_quarto_helpers.py
"""Testes pros helpers compartilhados dos notebooks Quarto.

Cobre 3 familias:
1. Formatters puros (fmt_pct, fmt_int, safe_int) — sem dependencias
2. Schema/query (has_col, has_view, table_count) — DuckDB in-memory
3. Setup (setup_views_with_manual, setup_notebook) — parquets em tmpdir

Bugs de regressao cobertos:
- `safe_int(NaN)` → 0 (era TypeError no `int(... or 0)` original)
- `setup_notebook` com account_filter NAO recursivo (era infinite recursion
  no DuckDB binder quando fazia CREATE VIEW X AS SELECT FROM X)
- `setup_views_with_manual` UNION ALL BY NAME tolera schema divergente
  (manual tem capture_method, extractor antigo nao)
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.parsers.quarto_helpers import (
    fmt_pct,
    fmt_int,
    safe_int,
    has_col,
    has_view,
    table_count,
    setup_views_with_manual,
    setup_notebook,
)


# === Formatters ===


class TestFmtPct:
    def test_normal_case(self):
        assert fmt_pct(50, 100) == "50/100 (50%)"

    def test_zero_division_safe(self):
        assert fmt_pct(0, 0) == "0/0 (0%)"

    def test_full_coverage(self):
        assert fmt_pct(1171, 1171) == "1,171/1,171 (100%)"

    def test_separator_thousands(self):
        # 1234 -> "1,234"
        assert fmt_pct(1234, 5678) == "1,234/5,678 (22%)"

    def test_rounds_down(self):
        # 1/3 = 33.33...% -> "33%"
        assert fmt_pct(1, 3) == "1/3 (33%)"


class TestFmtInt:
    def test_int(self):
        assert fmt_int(1234) == "1,234"

    def test_float(self):
        assert fmt_int(1234.0) == "1,234"

    def test_none_returns_dash(self):
        assert fmt_int(None) == "—"

    def test_nan_returns_dash(self):
        assert fmt_int(float("nan")) == "—"

    def test_zero(self):
        assert fmt_int(0) == "0"

    def test_string_int(self):
        # Aceita string numerica
        assert fmt_int("42") == "42"

    def test_string_invalid_returns_input(self):
        # Fallback: retorna repr da entrada
        assert fmt_int("abc") == "abc"


class TestSafeInt:
    def test_int(self):
        assert safe_int(42) == 42

    def test_float(self):
        assert safe_int(42.7) == 42

    def test_none_default_zero(self):
        assert safe_int(None) == 0

    def test_nan_default_zero(self):
        # Regressao: era TypeError no `int(NaN or 0)` original
        assert safe_int(float("nan")) == 0

    def test_custom_default(self):
        assert safe_int(None, default=-1) == -1
        assert safe_int(float("nan"), default=99) == 99

    def test_string_numeric(self):
        assert safe_int("42") == 42

    def test_string_invalid_default(self):
        assert safe_int("abc") == 0
        assert safe_int("abc", default=10) == 10

    def test_empty_string_default(self):
        assert safe_int("") == 0


# === Schema/query ===


@pytest.fixture
def con():
    """DuckDB in-memory com tabela de teste."""
    c = duckdb.connect()
    c.execute("CREATE TABLE foo (id INT, title VARCHAR, account VARCHAR)")
    c.execute("INSERT INTO foo VALUES (1, 'hello', 'a'), (2, 'world', 'b')")
    yield c
    c.close()


class TestHasCol:
    def test_existing_col(self, con):
        assert has_col(con, "foo", "id") is True
        assert has_col(con, "foo", "title") is True

    def test_missing_col(self, con):
        assert has_col(con, "foo", "nonexistent") is False

    def test_table_doesnt_exist(self, con):
        assert has_col(con, "ghost_table", "id") is False


class TestHasView:
    def test_existing_table(self, con):
        assert has_view(con, "foo") is True

    def test_missing_table(self, con):
        assert has_view(con, "ghost") is False

    def test_view(self, con):
        con.execute("CREATE VIEW foo_v AS SELECT * FROM foo")
        assert has_view(con, "foo_v") is True


class TestTableCount:
    def test_normal(self, con):
        assert table_count(con, "foo") == 2

    def test_missing_table_returns_zero(self, con):
        # Importante: usado no template pra render condicional
        assert table_count(con, "ghost") == 0

    def test_empty_table(self, con):
        con.execute("CREATE TABLE empty_t (x INT)")
        assert table_count(con, "empty_t") == 0


# === Setup ===


@pytest.fixture
def parquet_dir(tmp_path):
    """Diretorio temp com parquets de teste de uma source 'fake'.

    Layout:
      <tmp>/fake_conversations.parquet      (extractor, 3 rows, sem capture_method)
      <tmp>/fake_manual_conversations.parquet  (manual, 2 rows, com capture_method)
      <tmp>/fake_messages.parquet           (extractor, 5 rows)
      <tmp>/fake_branches.parquet           (extractor, 3 rows)
      (tool_events nao existe — testa caso "no parquet")
    """
    base = tmp_path / "processed"
    base.mkdir()

    # Extractor: schema antigo (sem capture_method) com account
    convs_ext = pd.DataFrame({
        "conversation_id": ["c1", "c2", "c3"],
        "source": ["fake"] * 3,
        "title": ["Hello", "World", "Test"],
        "account": ["1", "1", "2"],
        "message_count": [5, 3, 1],
    })
    convs_ext.to_parquet(base / "fake_conversations.parquet")

    # Manual: schema novo com capture_method
    convs_manual = pd.DataFrame({
        "conversation_id": ["c4", "c5"],
        "source": ["fake"] * 2,
        "title": ["Manual1", "Manual2"],
        "account": ["1", "2"],
        "message_count": [2, 4],
        "capture_method": ["manual_clipping_obsidian", "manual_copypaste"],
    })
    convs_manual.to_parquet(base / "fake_manual_conversations.parquet")

    msgs = pd.DataFrame({
        "message_id": [f"m{i}" for i in range(5)],
        "conversation_id": ["c1", "c1", "c2", "c2", "c3"],
        "source": ["fake"] * 5,
        "role": ["user", "assistant"] * 2 + ["user"],
        "account": ["1", "1", "1", "1", "2"],
    })
    msgs.to_parquet(base / "fake_messages.parquet")

    branches = pd.DataFrame({
        "branch_id": ["c1_main", "c2_main", "c3_main"],
        "conversation_id": ["c1", "c2", "c3"],
        "source": ["fake"] * 3,
    })
    branches.to_parquet(base / "fake_branches.parquet")

    return base


class TestSetupViewsWithManual:
    def test_extractor_only(self, parquet_dir):
        con = duckdb.connect()
        detected = setup_views_with_manual(
            con, "fake", parquet_dir, ["messages", "branches"]
        )
        assert detected["messages"] == {"extractor": True, "manual": False}
        assert table_count(con, "messages") == 5

    def test_extractor_plus_manual_unioned(self, parquet_dir):
        """UNION ALL BY NAME deve juntar 3 + 2 = 5 convs."""
        con = duckdb.connect()
        detected = setup_views_with_manual(
            con, "fake", parquet_dir, ["conversations"]
        )
        assert detected["conversations"] == {"extractor": True, "manual": True}
        assert table_count(con, "conversations") == 5

    def test_schema_divergent_capture_method_null_extractor(self, parquet_dir):
        """Extractor antigo nao tem capture_method — UNION BY NAME deve produzir
        coluna na view com NULL pras rows do extractor."""
        con = duckdb.connect()
        setup_views_with_manual(con, "fake", parquet_dir, ["conversations"])
        # capture_method existe na view (vem do manual)
        assert has_col(con, "conversations", "capture_method") is True
        # 3 rows com capture_method NULL (extractor) + 2 com valor (manual)
        n_null = con.execute(
            "SELECT COUNT(*) FROM conversations WHERE capture_method IS NULL"
        ).fetchone()[0]
        n_set = con.execute(
            "SELECT COUNT(*) FROM conversations WHERE capture_method IS NOT NULL"
        ).fetchone()[0]
        assert n_null == 3
        assert n_set == 2

    def test_missing_table_no_view_created(self, parquet_dir):
        con = duckdb.connect()
        detected = setup_views_with_manual(
            con, "fake", parquet_dir, ["tool_events"]
        )
        assert detected["tool_events"] == {"extractor": False, "manual": False}
        assert has_view(con, "tool_events") is False


class TestSetupNotebook:
    def test_no_account_filter_returns_all(self, parquet_dir):
        con = duckdb.connect()
        result = setup_notebook(
            con, "fake", parquet_dir,
            tables=["conversations", "messages"],
            aux_tables=[],
        )
        assert table_count(con, "conversations") == 5
        assert table_count(con, "messages") == 5
        assert result["has_capture_method"] is True
        assert result["has_account"] is True  # account-1 e account-2 distintas

    def test_account_filter_one(self, parquet_dir):
        """Filter '1' deve restringir tudo a account-1."""
        con = duckdb.connect()
        setup_notebook(
            con, "fake", parquet_dir,
            tables=["conversations", "messages"],
            account_filter="1",
        )
        # 2 do extractor (c1, c2) + 1 do manual (c4) = 3
        assert table_count(con, "conversations") == 3
        # 4 msgs do extractor pra account-1 (m0,m1,m2,m3)
        assert table_count(con, "messages") == 4

    def test_account_filter_two(self, parquet_dir):
        con = duckdb.connect()
        setup_notebook(
            con, "fake", parquet_dir,
            tables=["conversations", "messages"],
            account_filter="2",
        )
        # 1 do extractor (c3) + 1 do manual (c5) = 2
        assert table_count(con, "conversations") == 2
        # 1 msg account-2 (m4)
        assert table_count(con, "messages") == 1

    def test_account_filter_no_recursion(self, parquet_dir):
        """Regressao: setup_notebook com account_filter nao deve causar
        'infinite recursion detected: attempting to recursively bind view'."""
        con = duckdb.connect()
        # Se causar recursao, o setup levanta DuckDB BinderException
        setup_notebook(
            con, "fake", parquet_dir,
            tables=["conversations"],
            account_filter="1",
        )
        # Tem que conseguir consultar normalmente
        df = con.execute("SELECT * FROM conversations").df()
        assert len(df) == 3

    def test_account_filter_sql_injection_safe(self, parquet_dir):
        """Aspas simples no filter sao escaped corretamente."""
        con = duckdb.connect()
        # Filter com aspa nao deve quebrar SQL — vai retornar zero rows
        setup_notebook(
            con, "fake", parquet_dir,
            tables=["conversations"],
            account_filter="' OR '1'='1",  # tentativa de injection
        )
        # SQL injection bloqueada -> 0 rows (nenhum match literal)
        assert table_count(con, "conversations") == 0

    def test_aux_tables_loaded(self, tmp_path):
        """Aux tables sao carregadas como views separadas."""
        base = tmp_path / "processed"
        base.mkdir()
        # Source principal + aux
        convs = pd.DataFrame({
            "conversation_id": ["c1"], "source": ["fake"],
            "title": ["x"], "account": ["1"],
        })
        convs.to_parquet(base / "fake_conversations.parquet")

        notes = pd.DataFrame({
            "note_id": ["n1", "n2"],
            "conversation_id": ["c1", "c1"],
            "source": ["fake"] * 2,
            "kind": ["note", "brief"],
        })
        notes.to_parquet(base / "fake_notes.parquet")

        con = duckdb.connect()
        setup_notebook(
            con, "fake", base,
            tables=["conversations"],
            aux_tables=["notes"],
        )
        assert has_view(con, "notes") is True
        assert table_count(con, "notes") == 2

    def test_no_aux_means_no_aux_view(self, parquet_dir):
        """Sem aux_tables, views auxiliares nao sao criadas."""
        con = duckdb.connect()
        setup_notebook(
            con, "fake", parquet_dir,
            tables=["conversations"],
            aux_tables=[],
        )
        assert has_view(con, "notes") is False
        assert has_view(con, "outputs") is False
