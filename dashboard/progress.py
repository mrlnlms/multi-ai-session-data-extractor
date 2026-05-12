"""Parser de progresso a partir do stdout dos syncs.

Quase todos os extractors emitem linhas no formato `[done/total]` (fetchers
das 9 plataformas + asset_downloaders de Grok/Kimi + orchestrator do
NotebookLM). O asset_downloader do NotebookLM usa formato proprio:
`progresso: done/total (...)`.

`parse_progress(line)` devolve `(done, total)` se conseguir extrair um
sinal de progresso, ou `None`. Usado pelo dashboard pra atualizar uma
barra `st.progress` por plataforma em tempo real, sem precisar mexer nos
extractors.
"""
from __future__ import annotations

import re
from typing import Optional

# `[done/total]` — pattern dominante (fetchers de todas as plataformas
# + asset_downloaders de Grok/Kimi + orchestrator NotebookLM).
_BRACKET_RE = re.compile(r"\[(\d+)\s*/\s*(\d+)\]")

# `progresso: done/total` — NotebookLM asset_downloader.
_NLM_ASSET_RE = re.compile(r"progresso:\s*(\d+)\s*/\s*(\d+)")


def parse_progress(line: str) -> Optional[tuple[int, int]]:
    """Devolve (done, total) se a linha carrega sinal de progresso."""
    m = _BRACKET_RE.search(line) or _NLM_ASSET_RE.search(line)
    if not m:
        return None
    done, total = int(m.group(1)), int(m.group(2))
    if total <= 0:
        return None
    return done, total
