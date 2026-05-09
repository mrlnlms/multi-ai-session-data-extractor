#!/usr/bin/env python
"""Materializa data/unified/ a partir de data/processed/<Plataforma>/.

Junta parquets per-source num parquet unificado por tabela. Idempotente —
sempre regenera do zero a partir do que esta em processed/.

Pipeline:
    extractor -> reconciler -> parser     -> unify
       raw    ->   merged   -> processed -> unified

Uso:
    PYTHONPATH=. .venv/bin/python scripts/unify-parquets.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# Tabelas canonicas + auxiliares + chave primaria composta pra dedup.
# PK sempre inclui `source` (separa plataformas) e `conversation_id` ou
# `project_id` quando a tabela eh "filha" — porque algumas plataformas
# usam IDs locais por conv (DeepSeek `message_id` int 1-98; Claude Code
# subagents reusam message_id do parent quando compactam sessao).
TABLE_PKS: dict[str, list[str]] = {
    # 4 canonicas
    "conversations":    ["source", "conversation_id"],
    "messages":         ["source", "conversation_id", "message_id"],
    "tool_events":      ["source", "conversation_id", "event_id"],
    "branches":         ["source", "conversation_id", "branch_id"],
    # 5 auxiliares NotebookLM (filhas de conv ou de project)
    "sources":          ["source", "project_id", "doc_id"],   # filha de notebook(project)
    "notes":            ["source", "conversation_id", "note_id"],
    "outputs":          ["source", "conversation_id", "output_id"],
    "guide_questions":  ["source", "conversation_id", "question_id"],
    "source_guides":    ["source", "conversation_id", "source_id"],
    # 2 auxiliares Qwen/Claude.ai (filhas de project)
    "project_metadata": ["source", "project_id"],
    "project_docs":     ["source", "project_id", "doc_id"],
    # Mapping conv -> project (cross-platform tagging)
    "conversation_projects": ["source", "conversation_id", "project_tag"],
    # 1 auxiliar Claude Code/Codex (memorias do agente)
    "agent_memories":   ["source", "memory_id"],
}

# Ordenado por len(table) DESC pra match seguro:
# 'source_guides' (13) precisa ser testado antes de 'sources' (7),
# senao 'notebooklm_source_guides.parquet' bateria com 'sources'.
_TABLES_BY_LEN = sorted(TABLE_PKS.keys(), key=len, reverse=True)


def _identify_table(parquet_path: Path) -> str | None:
    """Identifica a tabela canonica pelo sufixo do nome do arquivo.

    >>> _identify_table(Path('chatgpt_conversations.parquet'))
    'conversations'
    >>> _identify_table(Path('notebooklm_manual_messages.parquet'))
    'messages'
    >>> _identify_table(Path('notebooklm_source_guides.parquet'))
    'source_guides'
    """
    stem = parquet_path.stem
    for table in _TABLES_BY_LEN:
        if stem.endswith(f"_{table}"):
            return table
    return None


def _source_from_path(parquet_path: Path) -> str:
    """Extrai source do filename.

    >>> _source_from_path(Path('qwen_project_metadata.parquet'))
    'qwen'
    >>> _source_from_path(Path('claude_ai_manual_conversations.parquet'))
    'claude_ai'
    """
    stem = parquet_path.stem
    table = _identify_table(parquet_path)
    if table is None:
        return ""
    base = stem[: -len(f"_{table}")]
    if base.endswith("_manual"):
        base = base[: -len("_manual")]
    return base


def discover_parquets(processed_dir: Path) -> dict[str, list[Path]]:
    """Mapeia tabela -> [parquets descobertos] em data/processed/<Plataforma>/.

    Inclui extractor (`<source>_<table>.parquet`) e manual saves
    (`<source>_manual_<table>.parquet`). Arquivos sem match em TABLE_PKS
    geram warning e sao ignorados.
    """
    by_table: dict[str, list[Path]] = {t: [] for t in TABLE_PKS}
    for plat_dir in sorted(processed_dir.iterdir()):
        if not plat_dir.is_dir():
            continue
        for f in sorted(plat_dir.glob("*.parquet")):
            table = _identify_table(f)
            if table is None:
                logger.warning(f"unknown table for {f} — skipped")
                continue
            by_table[table].append(f)
    return by_table


def unify_table(table: str, files: list[Path]) -> pd.DataFrame:
    """Concat + dedup pra UMA tabela. Retorna o DataFrame final."""
    pk_cols = TABLE_PKS[table]
    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        # Enriquece com source quando ausente (caso project_metadata)
        if "source" not in df.columns:
            df = df.assign(source=_source_from_path(f))
        dfs.append(df)

    merged = pd.concat(dfs, ignore_index=True)

    # Dedup pela PK composta keep='last'. Dois cenarios atendidos:
    # 1. Defesa contra dup interna no parquet upstream (bug de parser que
    #    emite a mesma row 2x — observado empiricamente em
    #    claude_code/gemini_cli_conversations).
    # 2. Fix de parser propaga (rodar parse 2x sem limpar produz rows novas
    #    que sobrescrevem antigas).
    # Em colisao extractor↔manual (hoje 0 ocorrencias na base): manual
    # ganharia (vem depois alfabeticamente: `_manual_<table>` > `_<table>`).
    # Quando aparecer caso real, decidir explicitamente — provavelmente
    # extractor deveria ganhar (mais completo).
    before = len(merged)
    pk_present = [c for c in pk_cols if c in merged.columns]
    if pk_present:
        merged = merged.drop_duplicates(subset=pk_present, keep="last")
    dupes = before - len(merged)
    if dupes:
        logger.info(f"  {table}: {dupes} duplicatas removidas (PK={pk_present})")
    return merged


def unify(processed_dir: Path, unified_dir: Path) -> dict[str, int]:
    """Materializa data/unified/<table>.parquet pra cada tabela presente.

    Returns: {table: row_count} de cada arquivo escrito.
    """
    unified_dir.mkdir(parents=True, exist_ok=True)
    by_table = discover_parquets(processed_dir)

    counts: dict[str, int] = {}
    for table in TABLE_PKS:
        files = by_table.get(table, [])
        if not files:
            logger.info(f"  {table:20} (sem parquets — skipped)")
            continue

        merged = unify_table(table, files)
        out = unified_dir / f"{table}.parquet"
        merged.to_parquet(out, index=False)
        counts[table] = len(merged)
        size_mb = out.stat().st_size / 1024 / 1024
        logger.info(
            f"  {table:18} {len(merged):>7,} rows  "
            f"{size_mb:>5.1f} MB  ({len(files)} files concat)"
        )

    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    project_root = Path(__file__).parent.parent
    processed_dir = project_root / "data" / "processed"
    unified_dir = project_root / "data" / "unified"

    if not processed_dir.exists():
        raise SystemExit(
            f"ERROR: {processed_dir} nao existe — rode <plat>-parse.py antes"
        )

    print(f"unify: {processed_dir} -> {unified_dir}")
    print()
    counts = unify(processed_dir, unified_dir)

    print()
    print("=== summary ===")
    total = sum(counts.values())
    for table, n in counts.items():
        print(f"  {table:18} {n:>7,} rows")
    print(f"  {'TOTAL':18} {total:>7,}")


if __name__ == "__main__":
    main()
