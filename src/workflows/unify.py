#!/usr/bin/env python
"""Materialize ``data/unified`` from per-platform processed Parquets.

Junta parquets per-source num parquet unificado por tabela. Idempotente —
sempre regenera do zero a partir do que esta em processed/.

Pipeline:
    extractor -> reconciler -> parser     -> unify
       raw    ->   merged   -> processed -> unified

Uso:
    PYTHONPATH=. .venv/bin/python -m src.workflows.unify
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import json

from src.runtime.project import find_project_root

import pandas as pd

from src.schema.models import (
    VALID_ASSET_LINK_OBJECT_TYPES,
    VALID_ASSET_LINK_ROLES,
    VALID_ASSET_ORIGINS,
)

logger = logging.getLogger(__name__)


# Tabelas canonicas + auxiliares + chave primaria composta pra dedup.
# PK sempre inclui `source`, `account_id` (separa contas) e `conversation_id` ou
# `project_id` quando a tabela eh "filha" — porque algumas plataformas
# usam IDs locais por conv (DeepSeek `message_id` int 1-98; Claude Code
# subagents reusam message_id do parent quando compactam sessao).
TABLE_PKS: dict[str, list[str]] = {
    # 4 canonicas
    "conversations":    ["source", "account_id", "conversation_id"],
    "messages":         ["source", "account_id", "conversation_id", "message_id"],
    "tool_events":      ["source", "account_id", "conversation_id", "event_id"],
    "branches":         ["source", "account_id", "conversation_id", "branch_id"],
    # 5 auxiliares NotebookLM (filhas de conv ou de project)
    "sources":          ["source", "account_id", "project_id", "doc_id"],
    "notes":            ["source", "account_id", "conversation_id", "note_id"],
    "outputs":          ["source", "account_id", "conversation_id", "output_id"],
    "guide_questions":  ["source", "account_id", "conversation_id", "question_id"],
    "source_guides":    ["source", "account_id", "conversation_id", "source_id"],
    # 2 auxiliares Qwen/Claude.ai (filhas de project)
    "project_metadata": ["source", "account_id", "project_id"],
    "project_docs":     ["source", "account_id", "project_id", "doc_id"],
    # Mapping conv -> project (cross-platform tagging)
    "conversation_projects": ["source", "account_id", "conversation_id", "project_tag"],
    # 1 auxiliar Claude Code/Codex (memorias do agente)
    "agent_memories":   ["source", "account_id", "memory_id"],
    # Canonical asset catalog and evidence-backed domain relationships
    "assets":           ["source", "account_id", "asset_id"],
    "asset_links":      ["source", "account_id", "asset_link_id"],
}

# Ordenado por len(table) DESC pra match seguro:
# 'source_guides' (13) precisa ser testado antes de 'sources' (7),
# senao 'notebooklm_source_guides.parquet' bateria com 'sources'.
_TABLES_BY_LEN = sorted(TABLE_PKS.keys(), key=len, reverse=True)


def _identify_table(parquet_path: Path) -> str | None:
    """Identifica a tabela canonica pelo sufixo do nome do arquivo.

    >>> _identify_table(Path('chatgpt_conversations.parquet'))
    'conversations'
    >>> _identify_table(Path('chatgpt_manual_messages.parquet'))
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
        # Compatibility with pre-migration and CLI/manual Parquets. Never
        # synthesize identity from the legacy display `account` column.
        if "account_id" not in df.columns:
            df = df.assign(account_id=pd.NA)
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


def _validate_account_integrity(frames: dict[str, pd.DataFrame]) -> None:
    """Reject non-null child identities that disagree with their conversation."""
    conversations = frames.get("conversations")
    if conversations is None or conversations.empty:
        return
    parent_keys = set(zip(conversations["source"], conversations["conversation_id"]))
    parent_identities = set(
        zip(
            conversations.loc[conversations["account_id"].notna(), "source"],
            conversations.loc[conversations["account_id"].notna(), "conversation_id"],
            conversations.loc[conversations["account_id"].notna(), "account_id"],
        )
    )
    for table, child in frames.items():
        if table == "conversations" or "conversation_id" not in child.columns:
            continue
        mismatches = sum(
            1
            for row in child.loc[child["account_id"].notna()].itertuples(index=False)
            if (row.source, row.conversation_id) in parent_keys
            and (row.source, row.conversation_id, row.account_id) not in parent_identities
        )
        if mismatches:
            raise ValueError(
                f"account_id mismatch between conversations and {table}: "
                f"{mismatches} row(s)"
            )


def _identity(value) -> str | None:
    return None if pd.isna(value) else str(value)


def _validate_asset_integrity(
    frames: dict[str, pd.DataFrame], data_root: Path
) -> None:
    assets = frames.get("assets")
    links = frames.get("asset_links")
    if assets is None or assets.empty:
        if links is not None and not links.empty:
            raise ValueError("asset_links cannot exist without assets")
        return

    conversations = frames.get("conversations", pd.DataFrame())
    conversation_keys = {
        (str(row.source), _identity(row.account_id), str(row.conversation_id))
        for row in conversations.itertuples(index=False)
    }
    forbidden_metadata_keys = {
        "url", "uri", "token", "signature", "authorization", "cookie",
        "signurl", "signed_url", "upstream_url",
    }

    def metadata_values(value):
        if isinstance(value, dict):
            for nested in value.values():
                yield from metadata_values(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from metadata_values(nested)
        elif isinstance(value, str):
            yield value

    for row in assets.itertuples(index=False):
        account_id = _identity(row.account_id)
        if row.asset_origin not in VALID_ASSET_ORIGINS:
            raise ValueError(f"asset_origin is invalid: {row.asset_origin}")
        if row.asset_origin == "assistant" and (
            pd.isna(row.is_model_generated) or not bool(row.is_model_generated)
        ):
            raise ValueError("assistant asset_origin requires is_model_generated=True")
        if row.asset_origin == "user" and (
            pd.isna(row.is_model_generated) or bool(row.is_model_generated)
        ):
            raise ValueError("user asset_origin requires is_model_generated=False")
        asset_path = _identity(row.asset_path)
        if asset_path is not None:
            path = Path(asset_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"asset_path must be relative to data/: {asset_path}")
        if bool(row.is_binary_available):
            if asset_path is None or not (data_root / asset_path).is_file():
                raise ValueError(f"available asset_path does not resolve: {asset_path}")

        metadata_json = _identity(row.metadata_json)
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError as exc:
                raise ValueError("asset metadata_json must be valid JSON") from exc
            keys = {str(key).lower() for key in metadata} if isinstance(metadata, dict) else set()
            if keys & forbidden_metadata_keys:
                raise ValueError("asset metadata_json contains forbidden URL/credential material")
            lowered = metadata_json.lower()
            if "://" in lowered or "?x-amz-" in lowered or "?token=" in lowered:
                raise ValueError("asset metadata_json contains forbidden URL/credential material")
            if any(Path(value).is_absolute() for value in metadata_values(metadata)):
                raise ValueError("asset metadata_json contains an absolute local path")

    if links is None or links.empty:
        return
    asset_keys = {
        (str(row.source), _identity(row.account_id), str(row.asset_id))
        for row in assets.itertuples(index=False)
    }
    messages = frames.get("messages", pd.DataFrame())
    message_keys = {
        (str(row.source), _identity(row.account_id), str(row.conversation_id), str(row.message_id))
        for row in messages.itertuples(index=False)
    }
    projects = frames.get("project_metadata", pd.DataFrame())
    project_keys = {
        (str(row.source), _identity(row.account_id), str(row.project_id))
        for row in projects.itertuples(index=False)
    }
    sources = frames.get("sources", pd.DataFrame())
    source_keys = {
        (str(row.source), _identity(row.account_id), str(row.doc_id))
        for row in sources.itertuples(index=False)
    }
    project_docs = frames.get("project_docs", pd.DataFrame())
    source_keys.update({
        (str(row.source), _identity(row.account_id), str(row.doc_id))
        for row in project_docs.itertuples(index=False)
    })
    outputs = frames.get("outputs", pd.DataFrame())
    output_keys = {
        (str(row.source), _identity(row.account_id), str(row.output_id))
        for row in outputs.itertuples(index=False)
    }
    object_keys = {
        "conversation": conversation_keys,
        "project": project_keys,
        "source": source_keys,
        "output": output_keys,
    }
    for row in links.itertuples(index=False):
        prefix = (str(row.source), _identity(row.account_id))
        if row.object_type not in VALID_ASSET_LINK_OBJECT_TYPES:
            raise ValueError(f"asset_link object_type is invalid: {row.object_type}")
        if row.role not in VALID_ASSET_LINK_ROLES:
            raise ValueError(f"asset_link role is invalid: {row.role}")
        if _identity(row.message_id) is not None and _identity(row.conversation_id) is None:
            raise ValueError("asset_link message_id requires conversation_id")
        if pd.notna(row.content_block_index) and _identity(row.message_id) is None:
            raise ValueError("asset_link content_block_index requires message_id")
        asset_key = (*prefix, str(row.asset_id))
        if asset_key not in asset_keys:
            raise ValueError(f"asset_link asset_id does not resolve: {asset_key}")
        if row.object_type == "message":
            key = (*prefix, _identity(row.conversation_id), str(row.object_id))
            if key not in message_keys:
                raise ValueError(f"asset_link message does not resolve: {key}")
        else:
            key = (*prefix, str(row.object_id))
            if key not in object_keys[row.object_type]:
                raise ValueError(f"asset_link {row.object_type} does not resolve: {key}")


def unify(processed_dir: Path, unified_dir: Path) -> dict[str, int]:
    """Materializa data/unified/<table>.parquet pra cada tabela presente.

    Returns: {table: row_count} de cada arquivo escrito.
    """
    unified_dir.mkdir(parents=True, exist_ok=True)
    by_table = discover_parquets(processed_dir)

    frames: dict[str, pd.DataFrame] = {}
    file_counts: dict[str, int] = {}
    for table in TABLE_PKS:
        files = by_table.get(table, [])
        if not files:
            logger.info(f"  {table:20} (sem parquets — skipped)")
            continue

        frames[table] = unify_table(table, files)
        file_counts[table] = len(files)

    _validate_account_integrity(frames)
    _validate_asset_integrity(frames, processed_dir.parent)

    counts: dict[str, int] = {}
    for table, merged in frames.items():
        out = unified_dir / f"{table}.parquet"
        merged.to_parquet(out, index=False)
        counts[table] = len(merged)
        size_mb = out.stat().st_size / 1024 / 1024
        logger.info(
            f"  {table:18} {len(merged):>7,} rows  "
            f"{size_mb:>5.1f} MB  ({file_counts[table]} files concat)"
        )

    return counts


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    project_root = find_project_root(Path(__file__))
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
    return 0


if __name__ == "__main__":
    main()
