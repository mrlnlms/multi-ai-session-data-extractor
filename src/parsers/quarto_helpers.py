"""Helpers compartilhados pros notebooks Quarto descritivos.

Sao usados pelos qmds que fazem `{{< include _template.qmd >}}`.
Cada per-source qmd seta SOURCE_KEY/SOURCE_TITLE/SOURCE_COLOR/AUX_TABLES,
chama `setup_notebook(...)` e o template partial usa esses helpers pra
renderizar as secoes.

Exporta tres familias de helpers:

1. **Setup de views** — `setup_views_with_manual`, `setup_notebook`
   Cuidam de UNION extractor + manual saves, aux tables, account filter.
2. **Schema/query** — `has_col`, `has_view`, `table_count`
   Conditional rendering: secoes so aparecem se a coluna/tabela existe.
3. **Display/formatadores** — `fmt_pct`, `fmt_int`, `safe_int`,
   `show_df`, `show_md`, `plotly_bar`, `plotly_stacked_two`
   Tabelas estilizadas e graficos plotly consistentes em todos os qmds.

Decisao: helpers ficam aqui (modulo Python) em vez de inline no
_template.qmd porque o template eh chamado por 14 qmds — duplicar 50
linhas de helper em todos multiplicaria por 14 qualquer fix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import duckdb


# === Setup de views ===


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
        sql = f"CREATE OR REPLACE VIEW {table} AS {' UNION ALL BY NAME '.join(parts)}"
        con.execute(sql)

    return detected


def setup_unified_views(
    con: duckdb.DuckDBPyConnection,
    unified_dir: Path,
    sources_filter: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Carrega data/unified/*.parquet como VIEWs DuckDB pro overview cross-platform.

    Args:
        con: conexao DuckDB
        unified_dir: data/unified/ (output do scripts/unify-parquets.py)
        sources_filter: lista de sources (ex: ['chatgpt','claude_ai']) ou None
            pra todas. Aplicado via WHERE source IN (...) na criacao da view.

    Tabelas esperadas em unified_dir:
    - 4 canonicas: conversations, messages, tool_events, branches
    - 7 auxiliares: sources, notes, outputs, guide_questions, source_guides,
      project_metadata, project_docs

    Returns: {table: row_count} de cada view criada.
    """
    TABLES = [
        "conversations", "messages", "tool_events", "branches",
        "sources", "notes", "outputs", "guide_questions", "source_guides",
        "project_metadata", "project_docs",
    ]
    counts: dict[str, int] = {}
    for table in TABLES:
        p = unified_dir / f"{table}.parquet"
        if not p.exists():
            continue
        if sources_filter:
            quoted = ", ".join(f"'{s}'" for s in sources_filter)
            sql = (
                f"CREATE OR REPLACE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{p}') WHERE source IN ({quoted})"
            )
        else:
            sql = (
                f"CREATE OR REPLACE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{p}')"
            )
        con.execute(sql)
        counts[table] = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return counts


def setup_notebook(
    con: duckdb.DuckDBPyConnection,
    source_slug: str,
    processed_dir: Path,
    tables: list[str],
    aux_tables: Optional[list[str]] = None,
    account_filter: Optional[str] = None,
) -> dict[str, Any]:
    """Setup completo de views pro notebook descritivo.

    1. Carrega views via setup_views_with_manual (UNION com manual saves)
    2. Carrega aux tables (com UNION manual quando aplicavel — NotebookLM legacy)
    3. Aplica filtro de conta quando account_filter != None — recria views
       lendo dos parquets com WHERE account = '<val>'
       (NAO usa CREATE VIEW X AS SELECT FROM X — daria recursao no DuckDB)

    Retorna dict com:
    - detected: {table: {extractor, manual}} do helper original
    - has_capture_method: bool — se a view conversations tem a coluna
    - has_account: bool — se ha mais de uma conta (>1 distinct)
    """
    aux_tables = aux_tables or []
    detected = setup_views_with_manual(con, source_slug, processed_dir, tables)

    # Aux tables: tambem suportam UNION com manual saves (NotebookLM legacy
    # tem notebooklm_manual_sources/notes/outputs/etc)
    for t in aux_tables:
        p_ext = processed_dir / f"{source_slug}_{t}.parquet"
        p_manual = processed_dir / f"{source_slug}_manual_{t}.parquet"
        parts = []
        if p_ext.exists():
            parts.append(f"SELECT * FROM read_parquet('{p_ext}')")
        if p_manual.exists():
            parts.append(f"SELECT * FROM read_parquet('{p_manual}')")
        if parts:
            con.execute(
                f"CREATE OR REPLACE VIEW {t} AS "
                + " UNION ALL BY NAME ".join(parts)
            )

    # Aplica filtro de account quando solicitado — recria view do zero
    # lendo dos parquets, evitando recursao (CREATE VIEW X AS SELECT FROM X).
    if account_filter is not None:
        for t in tables + aux_tables:
            if not has_view(con, t):
                continue
            if not has_col(con, t, "account"):
                continue
            p_ext = processed_dir / f"{source_slug}_{t}.parquet"
            p_manual = processed_dir / f"{source_slug}_manual_{t}.parquet"
            parts = []
            if p_ext.exists():
                parts.append(f"SELECT * FROM read_parquet('{p_ext}')")
            if p_manual.exists():
                parts.append(f"SELECT * FROM read_parquet('{p_manual}')")
            if parts:
                _safe = account_filter.replace("'", "''")
                _src = " UNION ALL BY NAME ".join(parts)
                con.execute(
                    f"CREATE OR REPLACE VIEW {t} AS "
                    f"SELECT * FROM ({_src}) WHERE account = '{_safe}'"
                )

    has_capture = has_col(con, "conversations", "capture_method")
    has_account_data = False
    if has_col(con, "conversations", "account"):
        n_acc = con.execute(
            "SELECT COUNT(DISTINCT account) FROM conversations WHERE account IS NOT NULL"
        ).fetchone()[0]
        has_account_data = n_acc > 1

    return {
        "detected": detected,
        "has_capture_method": has_capture,
        "has_account": has_account_data,
    }


# === Schema/query ===


def has_col(con: duckdb.DuckDBPyConnection, table: str, col: str) -> bool:
    """True se a view/tabela tem a coluna."""
    try:
        cols = con.execute(f"DESCRIBE SELECT * FROM {table}").df()["column_name"].tolist()
        return col in cols
    except duckdb.Error:
        return False


def has_view(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    """True se a view existe (criada pelo setup)."""
    try:
        con.execute(f"SELECT 1 FROM {name} LIMIT 0")
        return True
    except duckdb.Error:
        return False


def table_count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """COUNT(*) ou 0 se a tabela nao existir."""
    if not has_view(con, table):
        return 0
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# === Formatters ===


def fmt_pct(n: int, total: int) -> str:
    """'n/total (XX%)' — placeholder safe contra zero."""
    pct = n / total * 100 if total else 0
    return f"{n:,}/{total:,} ({pct:.0f}%)"


def fmt_int(n: Any) -> str:
    """Inteiro com separador de milhar, '—' se None/NaN."""
    try:
        if n is None:
            return "—"
        import math
        if isinstance(n, float) and math.isnan(n):
            return "—"
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def safe_int(n: Any, default: int = 0) -> int:
    """int(n) tolerante a None/NaN/string vazia."""
    try:
        if n is None:
            return default
        import math
        if isinstance(n, float) and math.isnan(n):
            return default
        return int(n)
    except (ValueError, TypeError):
        return default


# === Display ===


def show_df(df: Any, **kwargs: Any) -> None:
    """Mostra DataFrame com index oculto. Wrapper consistente."""
    from IPython.display import display

    display(df.style.hide(axis="index"))


def show_md(text: str) -> None:
    """Mostra Markdown inline (pra prosa condicional)."""
    from IPython.display import Markdown, display

    display(Markdown(text))


# === Plotting ===


def plotly_bar(
    x: Any,
    y: Any,
    title: str,
    color: str = "#74AA9C",
    height: int = 350,
    orientation: str = "v",
) -> Any:
    """Plotly bar chart consistente."""
    import plotly.graph_objects as go

    if orientation == "h":
        fig = go.Figure(go.Bar(y=x, x=y, marker_color=color, orientation="h"))
    else:
        fig = go.Figure(go.Bar(x=x, y=y, marker_color=color))
    fig.update_layout(
        title=title,
        height=height,
        template="plotly_white",
        margin=dict(t=50, b=40, l=40, r=20),
    )
    return fig


def plotly_stacked_two(
    x: Any,
    y_main: Any,
    y_other: Any,
    title: str,
    name_main: str,
    name_other: str,
    color_main: str = "#74AA9C",
    color_other: str = "#D1D5DB",
    height: int = 350,
    barmode: str = "stack",
) -> Any:
    """Bar chart com 2 series stacked (ex: com/sem campo X)."""
    import plotly.graph_objects as go

    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=y_main, name=name_main, marker_color=color_main))
    fig.add_trace(go.Bar(x=x, y=y_other, name=name_other, marker_color=color_other))
    fig.update_layout(
        barmode=barmode,
        title=title,
        height=height,
        template="plotly_white",
        margin=dict(t=50, b=80, l=40, r=20),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig
