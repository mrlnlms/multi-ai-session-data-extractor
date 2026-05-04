# Claude Code (CLI)

Source: `claude_code`. Mode: `cli`. Dado local (não captura web) — copy
incremental de `~/.claude/projects/`.

## Por quê não tem `server-behavior.md`

CLI não tem servidor. Comportamento de "rename/pin/delete" não se aplica
da mesma forma — sessões são arquivos JSONL no filesystem do user.

**Equivalentes pra CLI:**
- "Delete no servidor" → user apaga `<id>.jsonl` de `~/.claude/projects/`.
  `cli-copy.py` (linha 11 do docstring) preserva o arquivo já copiado em
  `data/raw/Claude Code/`. Parser pode marcar `is_preserved_missing=True`
  comparando raw vs HOME atual.

## Especificidades do schema

- `interaction_type='ai_ai'` pra subagents (sidechains) com
  `parent_session_id` apontando pro main session.
- **Threads compactadas (`/compact`):** N JSONLs com sessionId interno
  igual viram 1 Conversation com `conv_id=raiz`. Ver fix em
  `src/parsers/claude_code.py` (Fase 1: `_build_chain_links`).
- **Eventos repetidos no JSONL bruto:** dedup defensivo por `uuid`.

## Onde a info real mora

- **Parser:** `src/parsers/claude_code.py`
- **Copy script:** `src/extractors/cli/copy.py`
- **Quarto data profile:** `notebooks/claude-code.qmd`
- **Sync orquestrador:** `scripts/claude-code-sync.py`
