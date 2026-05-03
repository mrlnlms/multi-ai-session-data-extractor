"""Helpers pros notebooks Quarto descritivos.

setup_views_with_manual(): cria VIEWs DuckDB com UNION ALL BY NAME entre
parquets do extractor e parquets de manual saves (`<source>_manual_<table>.parquet`).
Schema divergente (capture_method ausente em parquets antigos) eh tratado
automaticamente — colunas missing viram NULL.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def setup_views_with_manual(
    con: duckdb.DuckDBPyConnection,
    source_slug: str,
    processed_dir: Path,
    tables: list[str],
) -> dict[str, dict[str, bool]]:
    """Cria VIEWs (1 por tabela) unindo extractor + manual saves quando ambos existirem.

    Args:
        con: conexao DuckDB
        source_slug: prefixo do parquet ('chatgpt', 'claude_ai', etc)
        processed_dir: data/processed/<Plataforma>/
        tables: ['conversations', 'messages', 'tool_events', 'branches']

    Returns: {table: {extractor: bool, manual: bool}} indicando quais existem.
    """
    detected: dict[str, dict[str, bool]] = {}
    for table in tables:
        p_ext = processed_dir / f"{source_slug}_{table}.parquet"
        p_manual = processed_dir / f"{source_slug}_manual_{table}.parquet"
        has_ext = p_ext.exists()
        has_manual = p_manual.exists()
        detected[table] = {"extractor": has_ext, "manual": has_manual}

        parts = []
        if has_ext:
            parts.append(f"SELECT * FROM read_parquet('{p_ext}')")
        if has_manual:
            parts.append(f"SELECT * FROM read_parquet('{p_manual}')")
        if not parts:
            continue
        # UNION ALL BY NAME alinha colunas pelo nome — schemas divergentes
        # (manual tem capture_method, extractor antigo nao) viram NULL.
        sql = f"CREATE VIEW {table} AS {' UNION ALL BY NAME '.join(parts)}"
        con.execute(sql)

    return detected
