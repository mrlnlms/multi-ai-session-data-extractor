"""Helper pra marcar `is_preserved_missing=True` em conversations CLI.

Padrao: cli-copy preserva arquivos em `data/raw/<CLI>/` mesmo quando o
user apaga do source HOME (`~/.claude/projects/`, `~/.codex/sessions/`,
`~/.gemini/tmp/`). Esse helper detecta isso comparando a lista de paths
parseados pela instancia do parser com a lista de arquivos atualmente
no HOME — se os arquivos de uma conv ja nao estao no HOME, marca
preservation.

Pre-requisito: o parser deve registrar relative paths em
`self._conv_source_files: dict[str, set[str]]` durante o `_parse_session`.
"""
from __future__ import annotations

import logging
from typing import Any

from src.extractors.cli.copy import current_source_files

logger = logging.getLogger(__name__)


def mark_cli_preservation(parser: Any) -> int:
    """Marca is_preserved_missing=True nas convs cujos arquivos source
    sumiram do HOME do CLI.

    Args:
        parser: instancia de CLI parser que populou `self._conv_source_files`
            durante o parse. Espera-se que `parser.source_name` seja
            'claude_code', 'codex' ou 'gemini_cli'.

    Returns: numero de conversations marcadas.

    Comportamento defensivo:
    - Se `current_source_files()` retorna set vazio (source HOME nao
      existe — ex: rodando em outra maquina sem o CLI instalado),
      pula silenciosamente sem marcar nada (nao temos como saber).
    - Se uma conv nao tem entrada em `_conv_source_files`, ignora.
    """
    current = current_source_files(parser.source_name)
    if not current:
        logger.info(
            f"  {parser.source_name}: source HOME ausente — preservation skipped"
        )
        return 0

    files_map: dict[str, set[str]] = getattr(parser, "_conv_source_files", {})
    n = 0
    for conv in parser.conversations:
        files = files_map.get(conv.conversation_id)
        if not files:
            continue
        # Se NENHUM dos arquivos da conv ainda esta no HOME → preserved
        if not (files & current):
            conv.is_preserved_missing = True
            n += 1
    if n:
        logger.info(
            f"  {parser.source_name}: {n} convs marcadas is_preserved_missing"
        )
    return n
