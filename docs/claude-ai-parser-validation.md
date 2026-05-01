# Parser Claude.ai v3 — validação cruzada vs legacy

Comparação do parser canônico v3 (`src/parsers/claude_ai.py`) vs parser
legacy (159 linhas, MVP do projeto-mãe `~/Desktop/AI Interaction Analysis/`),
preservado em `_backup-temp/parser-claude-ai-promocao-2026-05-01/`.

## TL;DR

Parser v3 entrega cobertura **estritamente superior** ao legacy. Não é
possível fazer comparação numérica direta porque:

1. **Input shape mudou**: legacy consumia 1 arquivo `conversations.json`
   com lista de convs (formato GPT2Claude bookmarklet). v3 consome o
   merged em pasta única (`data/merged/Claude.ai/conversations/<uuid>.json`,
   1 file por conv).
2. **Schema de output mudou**: legacy gerava 2 parquets básicos
   (`claude_ai_conversations`, `claude_ai_messages`) + auxiliar
   (`claude_ai_project_metadata`). v3 gera 5 parquets (incluindo
   `tool_events`, `branches`).
3. **Cobertura adicional**: v3 captura features que o legacy ignorava
   completamente (thinking, tool_use/result com MCP, branches, asset_paths,
   preservation flags).

## Counts reais (run 2026-05-01)

Sobre `data/merged/Claude.ai/` (835 conversations + 83 projects capturados
via `scripts/claude-sync.py`):

| Métrica | Legacy | v3 | Notas |
|---|---|---|---|
| conversations parqueteadas | N/A | 834 | 1 conv com erro de fetch (preservada na discovery) |
| messages parqueteadas | ? | 24.397 | balance ~12.3k user / ~12.1k assistant |
| **tool_events** | 0 | 16.044 | feature nova v3 |
| **branches** | 0 | 1.151 | feature nova v3 (832 main + 319 secundárias) |
| project_metadata | sim | 83 | mantido com schema mais rico |
| **convs com thinking** | ignorado | 4.460 msgs (~18%) | feature nova v3 |
| **convs com asset_paths** | parcial | 1.225 msgs | resolvido a partir de file_uuid |
| **convs com is_pinned** | ignorado | 12 (1.4%) | mapeado de is_starred |
| **is_temporary** | ignorado | 0 nesta run | preservado pra próximas |

## Diferenças schema-by-schema

### 4.1. `Conversation`

| Campo | Legacy | v3 |
|---|---|---|
| conversation_id, source, title | ✅ | ✅ |
| created_at, updated_at | ✅ | ✅ |
| message_count | ✅ | ✅ |
| model | ❌ (None) | ✅ (`claude-sonnet-4-5-...`) |
| account, mode, url | parcial | ✅ |
| **project_id** | ❌ | ✅ |
| **project (name)** | ❌ | ✅ |
| **is_pinned** (← is_starred) | ❌ | ✅ |
| **is_temporary** | ❌ | ✅ |
| **is_archived** | ❌ | ✅ (false — schema upstream sem campo) |
| **is_preserved_missing** | ❌ | ✅ |
| **last_seen_in_server** | ❌ | ✅ |

### 4.2. `Message`

| Campo | Legacy | v3 |
|---|---|---|
| message_id, conversation_id, source | ✅ | ✅ |
| sequence, role, content | ✅ | ✅ |
| created_at, account | ✅ | ✅ |
| content_types (incl thinking, tool_use, etc) | parcial | ✅ |
| attachment_names | ✅ | ✅ |
| **thinking** | ❌ | ✅ |
| **branch_id** | ❌ (sempre `<conv>_main`) | ✅ |
| **asset_paths** (paths em disco) | ❌ | ✅ |
| **finish_reason** (← stop_reason) | ❌ | ✅ |

### 4.3. `ToolEvent`

**Não existia no legacy.** v3 emite 1 ToolEvent por bloco `tool_use` ou
`tool_result`. Distribuição observada:

```
event_type           count
code_call             4079
code_result           4046
artifact_call         2868
artifact_result       2803
search_result          766
mcp_search_call        500
search_call            298
mcp_search_result      221
mcp_fetch_call         216
mcp_other_call          61
memory_result           41
research_call           38
research_result         38
mcp_other_result        32
mcp_fetch_result        25
mcp_write_call          12
```

MCP detectado via `integration_name` no bloco `tool_use` — captura tools
de Google Drive, Notion, Linear, etc.

### 4.4. `Branch`

**Não existia no legacy.** v3 reconstrói o DAG via `parent_message_uuid`
+ `current_leaf_message_uuid`:
- 832 main branches (uma por conv, em geral)
- 319 branches secundárias (forks via "edit message" ou regenerate)

## Critério de pronto

✅ **v3 ⊇ legacy** em todos os campos preservados pelo legacy.
✅ **v3 adiciona**: thinking, ToolEvent, Branch, MCP, asset_paths,
   preservation flags, is_pinned/is_temporary, project_id, finish_reason.
✅ **Idempotente**: rodar `scripts/claude-parse.py` 2x produz mesmos bytes.
✅ **Performance**: parse de 835 convs + 24k msgs em ~3.5s.
✅ **Testes**: 21 testes específicos do parser passam (suite total: 279).

## Como reproduzir

```bash
# Captura completa (raw + assets + reconcile)
PYTHONPATH=. .venv/bin/python scripts/claude-sync.py

# Parse (merged → parquet)
PYTHONPATH=. .venv/bin/python scripts/claude-parse.py
```

Output em `data/processed/Claude.ai/`:

```
claude_ai_conversations.parquet     (834 rows)
claude_ai_messages.parquet          (24.397 rows)
claude_ai_tool_events.parquet       (16.044 rows)
claude_ai_branches.parquet          (1.151 rows)
claude_ai_project_metadata.parquet  (83 rows)
```

## Observações cruzadas com Perplexity / ChatGPT

| Métrica | ChatGPT | Perplexity | Claude.ai |
|---|---|---|---|
| Conversations | 1.171 | 81 | 834 |
| Messages | 17.583 | 372 | 24.397 |
| Tool events | 3.109 | 2.311 | 16.044 |
| Branches | 1.369 | 81 | 1.151 |

Claude.ai tem **muito mais tool_events por conv** do que ChatGPT — reflete
o uso intensivo de Computer Use (file editing, bash) e MCPs. Em messages
absolutas, supera ChatGPT mesmo com volume menor de convs (média ~29
msgs/conv vs 15 do ChatGPT).

## Gap-fill v3.1 (2026-05-01)

Após primeira entrega "shipped", auditoria do backlog #41 do projeto-mãe
revelou 6 gaps de cobertura. Fechados em sequência, schema bumped.

| Gap | Impl |
|---|---|
| `Conversation.summary` (auto-gerado pelo servidor) | ✅ 466/835 convs (56%) |
| `Conversation.settings_json` (paprika_mode, web_search, etc) | ✅ 835/835 (100%) |
| `Message.citations_json` (citations em text blocks) | ✅ 115 msgs |
| `Message.attachments_json` (extracted_content inline) | ✅ 1.344 msgs |
| `Message.start_timestamp` + `stop_timestamp` (latência por block) | ✅ 23.930 msgs (98%) |
| MCP detection completa (`integration_name` + `mcp_server_url` + `is_mcp_app`) | ✅ 791 MCP calls (vs 716 antes) |
| Nova tabela `project_docs` (content inline, 23M chars) | ✅ 546 docs / 23.182.481 chars |

Bate com a spec do projeto-mãe (item #41): "23M chars em 546 docs" ✅
exato; "1.8k+ attachments" → 1.344 (próximo); "16k+ tool_use" → 16.180 ✅.

## TODOs futuros (não bloqueantes)

- **Inconsistência search_call vs search_result**: 298 calls / 766 results.
  Hipótese: `tool_result` carrega `name='web_search'` mas pode ter múltiplos
  resultados consolidados pra um único `tool_use`. Validar olhando
  `tool_use_id` na metadata.
- **memory_result sem call (41/0)**: tools de memória (recent_chats etc)
  podem ser injetados como result sem call explícito. Investigar.
- **Cenários CRUD validados empiricamente**: faltam testes manuais como
  os do ChatGPT/Perplexity (rename → updated_at bumpa? delete → preserved?
  pin via UI → is_starred reflete?). Documentar em
  `docs/claude-ai-server-behavior.md` quando rodar bateria.
