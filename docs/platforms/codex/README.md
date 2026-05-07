# Codex (CLI)

Source: `codex`. Mode: `cli`. Local data — incremental copy from
`~/.codex/sessions/`.

## Schema specifics

- **`function_call` ↔ `exec_command_end`** correlated via `call_id`
  → exact `duration_ms` + `success` per tool call.
- **`agent_reasoning`** accumulated becomes `thinking` of the next
  `agent_message`.

## Why there is no `server-behavior.md`

The CLI has no server. See `docs/platforms/claude-code/README.md` for
the "preservation at the raw level via cli-copy" pattern.

## Parquets gerados

- `codex_conversations.parquet`, `codex_messages.parquet`, `codex_tool_events.parquet`, `codex_branches.parquet` — schema canonico v3
- `codex_agent_memories.parquet` — le `data/raw/Codex/memories/**/*.md` (vazio hoje, schema valido pra populacao futura quando user comecar a usar Codex memory features)

## Where the real info lives

- **Parser:** `src/parsers/codex.py`
- **Copy script:** `src/extractors/cli/copy.py`
- **Quarto data profile:** `notebooks/codex.qmd`
- **Sync orchestrator:** `scripts/codex-sync.py`
