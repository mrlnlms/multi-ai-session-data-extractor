# Codex (CLI)

Source: `codex`. Mode: `cli`. Dado local — copy incremental de
`~/.codex/sessions/`.

## Especificidades do schema

- **`function_call` ↔ `exec_command_end`** correlacionados via `call_id`
  → `duration_ms` + `success` exatos por tool call.
- **`agent_reasoning`** acumulado vira `thinking` da próxima `agent_message`.

## Por quê não tem `server-behavior.md`

CLI não tem servidor. Ver `docs/platforms/claude-code/README.md` pra
padrão "preservation a nível de raw via cli-copy".

## Onde a info real mora

- **Parser:** `src/parsers/codex.py`
- **Copy script:** `src/extractors/cli/copy.py`
- **Quarto data profile:** `notebooks/codex.qmd`
- **Sync orquestrador:** `scripts/codex-sync.py`
