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
- `response_item.message` pode trazer imagens de entrada como data URI. O
  parser materializa os bytes em `data/raw/Codex/_images/`, verifica SHA-256
  antes de reutilizar um arquivo e publica `Asset` + `AssetLink` de entrada no
  bloco exato. Em rollouts mistos, a mensagem legada imediatamente adjacente
  recebe o vínculo sem duplicar a mensagem textual.

## Why there is no `server-behavior.md`

The CLI has no server. See `docs/extractor-engineering/platforms/cli/claude-code/state.md` for
the "preservation at the raw level via cli-copy" pattern.

## Parquets gerados

- `codex_conversations.parquet`, `codex_messages.parquet`, `codex_tool_events.parquet`, `codex_branches.parquet` — schema canonico v3
- `codex_agent_memories.parquet` — le `data/raw/Codex/memories/**/*.md`;
  a copia cumulativa preserva a arvore observada em `~/.codex/memories/`, e o
  parser mantem `project_path=NULL` porque a representacao atual e global
- `codex_agent_memory_versions.parquet` — versoes imutaveis por SHA-256
- `codex_agent_memory_temporal_evidence.parquet` — datas observadas e inferidas
  com base e confianca explicitas; `mtime` nunca e renomeado como criacao
- `codex_assets.parquet`, `codex_asset_links.parquet` — imagens de entrada
  embutidas e suas relações exatas com mensagens

## Cobertura do parser

Cada sync registra `files_seen`, `files_parsed` e `files_skipped` em
`capture_log.jsonl`. Um valor positivo em `files_skipped` deixa a plataforma
amarela no dashboard mesmo que o Parquet tenha sido escrito depois do raw;
isso evita declarar a pipeline saudavel quando um formato novo for descartado
silenciosamente.

## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Codex, reader scope is the inline input
image and its evidenced message position; unrelated filesystem paths are not
promoted to assets. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Where the real info lives

- **Parser:** `src/platforms/codex/parser.py`
- **Copy script:** `src/capture/cli/copy.py`
- **Quarto data profile:** `notebooks/codex.qmd`
- **Sync orchestrator:** `python -m src.platforms.codex.commands.sync`

## Limite historico

O periodo anterior ao manifesto v2 pode ser semeado com
`src.operations.reconstruct_agent_memory_history`; datas sem evidencia
permanecem nulas. Memories sao sinteses derivadas, nao substitutos das
conversas/rollouts que constituem evidencia primaria.
