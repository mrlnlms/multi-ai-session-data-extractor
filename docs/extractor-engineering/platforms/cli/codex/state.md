# Codex (CLI)

Source: `codex`. Mode: `cli`. Local data — incremental copy from
`~/.codex/sessions/`.

## Schema specifics

- **`function_call` ↔ `exec_command_end`** correlated via `call_id`
  → exact `duration_ms` + `success` per tool call.
- **`agent_reasoning`** accumulated becomes `thinking` of the next
  `agent_message`.
- Mensagens possuem duas codificacoes observadas:
  - rollouts legados: `event_msg.user_message` e
    `event_msg.agent_message`;
  - rollouts atuais: `response_item.message`, com `role=user|assistant` e
    partes `input_text|output_text` em `content`.
- A mudanca para rollouts contendo somente `response_item.message` foi
  observada em 2026-08-13. O parser prefere os eventos legados quando ambos
  existem na mesma sessao e usa `response_item.message` como fallback, evitando
  duplicacao. Mensagens de papel `developer` nao entram como mensagens da
  conversa.
- O primeiro `session_meta` identifica o rollout e coincide com o ID no nome
  do arquivo. Alguns rollouts atuais incorporam historico contendo um segundo
  `session_meta` de uma sessao anterior; esse meta posterior nao pode substituir
  a identidade do arquivo atual.

## Why there is no `server-behavior.md`

The CLI has no server. See `docs/extractor-engineering/platforms/cli/claude-code/state.md` for
the "preservation at the raw level via cli-copy" pattern.

## Parquets gerados

- `codex_conversations.parquet`, `codex_messages.parquet`, `codex_tool_events.parquet`, `codex_branches.parquet` — schema canonico v3
- `codex_agent_memories.parquet` — le `data/raw/Codex/memories/**/*.md` (vazio hoje, schema valido pra populacao futura quando user comecar a usar Codex memory features)

## Cobertura do parser

Cada sync registra `files_seen`, `files_parsed` e `files_skipped` em
`capture_log.jsonl`. Um valor positivo em `files_skipped` deixa a plataforma
amarela no dashboard mesmo que o Parquet tenha sido escrito depois do raw;
isso evita declarar a pipeline saudavel quando um formato novo for descartado
silenciosamente.

## Where the real info lives

- **Parser:** `src/platforms/codex/parser.py`
- **Copy script:** `src/capture/cli/copy.py`
- **Quarto data profile:** `notebooks/codex.qmd`
- **Sync orchestrator:** `python -m src.platforms.codex.commands.sync`
