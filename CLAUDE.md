# CLAUDE.md — contexto pra agentes que abrirem este projeto

## O que e este projeto

Captura completa e cumulativa de sessoes de AI multi-plataforma (ChatGPT,
Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity). Output em raw
JSON + binarios + parquet canonico. Pensado pra **capturar uma vez, deletar
do servidor, manter local como fonte primaria**.

Ver `README.md` pra setup e uso.

## SEMPRE refletir na UI do dashboard (Streamlit)

Toda vez que adicionar/promover plataforma (sync, parser v3, Quarto), **a
UI do dashboard Streamlit precisa refletir**. Nao basta criar arquivos —
abrir o dashboard e validar:

- `KNOWN_PLATFORMS` em `dashboard/data.py` lista a plataforma (ja lista as 7)
- Tabela cross-plataforma do overview mostra os 4 status verdes (capture +
  reconcile + parser + Quarto)
- Botao "Ver dados detalhados" aparece quando `notebooks/<source>.qmd` existe
- Counters batem com `LAST_CAPTURE.md` + `LAST_RECONCILE.md` + jsonls

Caminho default: `streamlit run dashboard/app.py` (ou comando equivalente
do projeto). Se nao reflete automaticamente, eh bug do dashboard — corrige
antes de declarar plataforma "shipped".

**Sintoma de que esqueci disso:** declarei plataforma pronta sem ter
aberto o dashboard. Furo: `notebooks/<source>.qmd` rendiriza, parquets
estao em `data/processed/<Source>/`, mas a tabela do dashboard ainda
mostra ❌. Resolver antes de fechar.

## Projeto pai — SEMPRE olhar la antes de criar do zero

Este projeto foi spawned de `~/Desktop/AI Interaction Analysis/` em 2026-04-27.
**Antes de criar QUALQUER coisa do zero aqui** (profile de login, fixture
baseline, config de captura, dados ancora pra debug, scripts equivalentes),
verificar primeiro se ja existe la. Cobre principalmente:

- **`.storage/<plat>-profile-*/`** — sessoes Playwright logadas pra todas as
  7 plataformas. Profile copiado vale (auth.py de cada extractor tem fallback
  pro nome legacy sem sufixo de account). NAO peca login do zero sem
  conferir.
- **`data/raw/<Plat>/`** e **`data/merged/<Plat>/`** — capturas anteriores
  servem de baseline / ground truth pra confronto com captura nova
  (especialmente quando a gente quer auditar gaps no extractor).
- **Configs e secrets** que nao estao versionados aqui ainda
  (cookies, API keys, etc).
- **Backup-temp** ou snapshots historicos quando precisar comparar
  comportamento antigo.

Princípio: o projeto pai e referencia operacional ate este aqui ficar
maduro pra rodar standalone. Reusar config local NAO contradiz o objetivo
opensource — quando o projeto for distribuido, cada usuario gera o proprio
profile/dados; o projeto pai e atalho de dev pra mim, nao parte do produto.

Lista de imports pendentes em `memory/project_pending_imports_from_old.md`.

## Status (2026-05-01)

| Plataforma | Capture | Reconcile | Sync orquestrador | Parser canonico | Quarto descritivo | Notas |
|---|---|---|---|---|---|---|
| ChatGPT | ✅ | ✅ | ✅ (4 etapas, pasta unica) | ✅ (Fase 2 done) | ✅ (Fase 3.1 done) | Preservation completa, rename detection, fail-fast, parser cobrindo branches + ToolEvents, data-profile renderizando |
| Claude.ai | ✅ | ✅ | ✅ (3 etapas, pasta unica) | ✅ v3 | ✅ | thinking, tool_use/result+MCP, branches via parent_uuid, is_pinned/is_temporary mapeados, 24k msgs / 16k events |
| Qwen | ✅ | ✅ | ✅ (2 etapas, pasta unica) | ✅ v3 | ✅ | 8 chat_types (t2t/search/research/t2i/t2v/artifacts/learn), reasoning_content, branches, projects c/ custom_instruction |
| DeepSeek | ✅ | ✅ | ✅ (2 etapas, pasta unica) | ✅ v3 | ✅ | R1 reasoning chain (222/722 msgs = 31%), token_count, branches via parent_id, search_results estruturados |
| Gemini | ✅ | ✅ | ❌ | ❌ | ❌ | Idem |
| NotebookLM | ✅ | ✅ | ❌ | ❌ | ❌ | 9 tipos de outputs (audio, video, slide deck PDF+PPTX, blog, flashcards, quiz, data table, infographic, mind map) |
| Perplexity | ✅ | ✅ | ✅ | ✅ | ✅ | Auditoria + reconciler + parser v3 + Quarto. 81 conversations (77 threads + 4 pages), 9 artifacts c/ binarios, 1 orphan, 4 spaces |
| Qwen / DeepSeek | ✅ | ❌ | ❌ | ❌ | ❌ | Reconcilers + sync pendentes |

Backlog principal: replicar o padrao do ChatGPT-sync nas outras 6 plataformas
+ parsers canonicos por plataforma (espelhar `src/parsers/chatgpt.py`).

## Estado validado em 2026-04-28 — NAO refazer

Antes de propor refatoracao ou script novo, conferir esta secao. O que esta
listado aqui **ja foi feito, testado e validado** — duplicar e desperdicio.

**ChatGPT — ciclo completo end-to-end validado:**
- Pasta unica cumulativa: `data/raw/ChatGPT/` e `data/merged/ChatGPT/`
- Sync v3 com 4 etapas (capture + assets + project_sources + reconcile)
- Os 6 cenarios CRUD validados empiricamente em 2026-04-27 e 2026-04-28:
  - Conv deletada → preserved_missing no merged
  - Conv atualizada (mensagem nova) → updated, update_time bumpado
  - Conv nova → added
  - Conv renomeada → updated (servidor bumpa update_time, mas guardrail extra
    no codigo cobre o caso edge de nao-bump)
  - Project criado → discovery sobe, novo g-p-* em project_sources/
  - Project deletado inteiro → todas as sources marcadas _preserved_missing,
    binarios fisicos intocados, chats internos preservados no merged
- Fail-fast contra discovery flakey (>20% drop aborta antes do save)
- 100 testes unitarios passando

**Perplexity — auditoria de extractor + Spaces (2026-04-29):**
- Profile reusado de `~/Desktop/AI Interaction Analysis/.storage/perplexity-profile/`
  (78MB, 24/abr — bate com fallback legacy do `auth.py` sem sufixo de account)
- **Bug pinned threads fixado:** `list_pinned_ask_threads` exige POST
  com body `{}`. GET retornava 400 silenciosamente. Confirmado via probe
  (7 variacoes testadas).
- **Spaces (collections) agora capturados:** novo modulo
  `src/extractors/perplexity/spaces.py`, 4 spaces salvos em
  `spaces/{uuid}/{metadata,threads_index,files}.json` + `spaces/_index.json`.
  Endpoints: `collections/list_user_collections`, `collections/get_collection`,
  `collections/list_collection_threads`, `file-repository/list-files`.
- **1 thread orphan detectada em GAS:** `d344c501-46aa-4951-85f7-6d27d2d4631d`
  (2024-09-02), referenciada em space mas deletada do servidor (HTTP 400
  ENTRY_NOT_FOUND). `list_collection_threads` preserva metadata mesmo de
  threads deletadas — fonte de preservation passiva.
- **NAO e cap temporal:** mais antiga em list_ask_threads e 2024-08-23
  (anterior ao orphan). Filtro parece ser presenca-no-servidor.
- **Computer/Scheduled/History — nada novo capturavel em conta free**:
  workflows/gallery sao templates globais, threads do Computer (mode=asi)
  ja estao em list_ask_threads.
- Findings empiricos em `docs/perplexity-audit-findings.md`.
- Probes em `scripts/perplexity-probe-features.py` e
  `scripts/perplexity-probe-spaces.py`.
- Pasta ainda com timestamp + nome legacy "Perplexity Data" (Fase A do
  plan de replicacao, nao feita ainda — escopo dessa auditoria foi so
  fechar gaps no extractor).

**Perplexity — ciclo completo end-to-end validado em 2026-05-01:**
- **Pasta unica cumulativa:** `data/raw/Perplexity/` e `data/merged/Perplexity/`
  (sem espaco no nome, sem timestamps)
- **Sync orquestrador 2 etapas:** `scripts/perplexity-sync.py` (capture + reconcile)
- **Cobertura completa:** threads (77) + spaces (4) + pages (4 dentro de Bookmarks)
  + threads em spaces + files de space (1) + assets/artifacts metadata (9)
  + assets binarios (9 baixados, ~1.9MB) + thread attachments (6 com manifest
  failed_upstream_deleted, S3 cleanup upstream — equivalente aos 8 do ChatGPT)
  + user metadata (info, settings, ai_profile)
- **Reconciler:** preservation completa (orphans + ENTRY_DELETED), idempotente,
  pasta unica `data/merged/Perplexity/perplexity_merged_summary.json` +
  LAST_RECONCILE.md + reconcile_log.jsonl
- **Parser canonico v3** (`src/parsers/perplexity.py`): 81 conversations
  (41 copilot + 36 concise + 4 research/pages), 372 messages, 2311 tool_events
  (2134 search_result + 168 media_reference + 9 asset_generation), 81 branches.
  Pages tem `conversation_id='page:<slug>'`. Search results extraidos de
  `blocks[*].web_result_block.web_results`. Idempotente (~1s pra rodar).
- **Quarto descritivo** (`notebooks/perplexity.qmd`): 22MB HTML self-contained
- **Findings empiricos:** `docs/perplexity-audit-findings.md`
- **Journey + dificuldades:** `docs/perplexity-journey-2026-05-01.md`
  (10 licoes transferiveis pras outras 5 plataformas)
- **Validacoes pendentes:** `docs/perplexity-pending-validations.md`
  (Parte 1: 8 acoes do user na proxima sessao sem Pro;
   Parte 2: 8 features Pro deferidas como TODO publico;
   Parte 3: 4 limitacoes upstream documentadas como nao-bug)
- **Probes:** 7 scripts em `scripts/perplexity-probe-*.py` (features, spaces,
  pages-*, artifacts, tabs-user, more)
- **Auth:** profile copiado do projeto pai (`.storage/perplexity-profile/`)
- **Comportamento do servidor mapeado:** rename bumpa `last_query_datetime`
  (igual ChatGPT), delete via menu = ENTRY_DELETED some de tudo, threads
  antigas em space podem virar orphan se deletadas (caso d344c501)
- **Bateria UI 2026-05-01 + probe direto Chrome MCP fechou 3 gaps:**
  - Pin de thread em library: bug em `list_all_threads` (seen como `set`
    em vez de `dict`) descartava `is_pinned: true` da thread quando ela
    ja aparecia em `list_ask_threads`. Fix: merge dict-based propaga
    flag. Validado: `d20e2c86` agora aparece com `is_pinned=True`.
  - Skills em spaces: endpoint `/rest/skills?scope=collection&scope_id=<UUID>`
    descoberto via probe (scope enum: `global`/`organization`/`collection`/
    `individual`). Implementado `list_collection_skills` + `list_user_skills`.
    Saida em `spaces/{uuid}/skills.json` e `user/skills.json`. Validado:
    1 skill `heatmap-explainer` capturado em Heatmaps Study.
  - Archive de thread: feature **Enterprise-only**. Endpoints write
    descobertos (`POST /rest/thread/archive_thread` body `{context_uuid}`
    + `DELETE /rest/thread/unarchive_thread/<context_uuid>`) e ate ACEITAM
    request de Pro (200 success), mas backend NAO expoe estado archived em
    `list_ask_threads` nem `fetch_thread` (testado: zero diff antes/depois).
    Frontend tenta carregar `restricted-feature-loader` que vai pra
    Cloudflare Access (zero-trust auth) — gated Enterprise. **Pra contas
    Pro: archive eh no-op observavel — sem gap no extractor.** Listagem
    archived fica TODO permanente Enterprise.
  - Voice em Perplexity: nao-bug, comportamento upstream (servidor
    transcreve e descarta audio, sem `is_voice` no schema).
- **Conta usada na bateria: Pro** (`display_model: pplx_pro_upgraded`).
- **Comandos:**
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/perplexity-sync.py
  PYTHONPATH=. .venv/bin/python scripts/perplexity-parse.py
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/perplexity.qmd
  ```

**Claude.ai — ciclo completo end-to-end validado em 2026-05-01:**
- **Pasta unica cumulativa:** `data/raw/Claude.ai/` e `data/merged/Claude.ai/`
  (sem timestamps, sem subpastas datadas)
- **Sync orquestrador 3 etapas:** `scripts/claude-sync.py` (capture + assets +
  reconcile)
- **Cobertura completa na captura:** 835 conversations + 83 projects descobertos
  e capturados (1 timeout transiente no full sync, recuperado via
  `scripts/claude-refetch-known.py` na primeira tentativa). 2.110 binarios
  baixados, 1.117 artifacts extraidos (code/markdown/html/react via tool_use)
- **Reconciler v3 (FEATURES_VERSION=2):** preservation completa (convs +
  projects), idempotente, pasta unica `data/merged/Claude.ai/conversations/<uuid>.json`
  + `projects/<uuid>.json` + `assets/`. Saida: `claude_ai_merged_summary.json`
  + `LAST_RECONCILE.md` + `reconcile_log.jsonl`
- **Parser canonico v3.1 — gap-fill backlog #41 do projeto-mae fechado**
  (`src/parsers/claude_ai.py` + `_claude_ai_helpers.py`):
  835 convs / 24.504 msgs / 16.180 tool_events / 1.160 branches / 83 projects /
  **546 project_docs (23.182.481 chars — bate exato com spec do pai)**.
  Cobertura:
  - **Branches via DAG plano** (`parent_message_uuid` + `current_leaf_message_uuid`)
    — diferente do tree-walk do ChatGPT. 832 main + 319 secundarias (28%
    convs com fork)
  - **Thinking blocks** preservados em `Message.thinking` (4.460 msgs)
  - **Tool use/result** → ToolEvent. Categorias observadas:
    `code_call/_result` (4k+ Computer Use/file editing), `artifact_call/_result`
    (2.8k cada), `search` (web_search + research), `mcp_*` (1.067 events
    em Google Drive e outros)
  - **MCP detection** via `integration_name` no tool_use block
  - **Attachments com extracted_content** preservados in-place no merged;
    parser registra file_names em `Message.attachment_names` (711 msgs)
  - **Files (uploads binarios)** → `Message.asset_paths` (1.225 msgs com
    paths resolvidos a partir de file_uuid)
  - **`is_starred` → `is_pinned`** (12 pinadas em 834 convs — cross-platform
    check)
  - **`is_temporary`** preservado (0 nesta run — feature efemera)
  - **Project metadata** em tabela auxiliar `claude_ai_project_metadata.parquet`
    (83 projects com docs_count + files_count + prompt_template)
  - **v3.1 (gap-fill 2026-05-01):**
    - `Conversation.summary` auto-gerado pelo servidor (466/835 = 56%)
    - `Conversation.settings_json` feature flags por conv (100%)
    - `Message.citations_json` citations em text blocks (115 msgs)
    - `Message.attachments_json` com extracted_content inline (1.344 msgs)
    - `Message.start_timestamp` + `stop_timestamp` latencia por block
      (23.930 msgs — 98% cobertura, mediana ~30s assistant)
    - MCP detection com 3 sinais (`integration_name` + `mcp_server_url`
      + `is_mcp_app`) — 791 MCP calls vs 716 antes
    - Nova tabela `claude_ai_project_docs.parquet` (546 docs / 23.182.481
      chars — content inline, queryable)
- **Quarto descritivo** (`notebooks/claude-ai.qmd`): 46MB HTML self-contained,
  render < 30s. Cor primaria: Anthropic burnt orange (#CC785C)
- **Findings empiricos:** `docs/claude-ai-parser-empirical-findings.md`
- **Validation cruzada vs legacy:** `docs/claude-ai-parser-validation.md`
  (parser v3 ⊇ legacy estritamente — adiciona thinking, tool_events,
  branches, MCP, asset_paths, preservation, is_pinned/is_temporary)
- **Backup do legacy:** `_backup-temp/parser-claude-ai-promocao-2026-05-01/`
- **Auth:** profile copiado de `~/Desktop/AI Interaction Analysis/.storage/claude-ai-profile-default/`
- **Captura headless** (sem Cloudflare challenge em runtime)
- **Comandos:**
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/claude-sync.py
  # Se o sync deixou gaps (timeouts transientes):
  PYTHONPATH=. .venv/bin/python scripts/claude-refetch-known.py
  PYTHONPATH=. .venv/bin/python scripts/claude-parse.py
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/claude-ai.qmd
  ```
- **TODOs validacao manual** (cenarios CRUD pendentes):
  - rename → servidor bumpa `updated_at`? (hipotese: sim)
  - delete → reconciler marca como `_preserved_missing`?
  - pin via UI → `is_starred=true` reflete em discovery?
  - temporary chat → comportamento na captura?
  - project archive → `archived_at` populado?

**Qwen — ciclo completo end-to-end validado em 2026-05-01:**
- **Pasta unica cumulativa:** `data/raw/Qwen/` e `data/merged/Qwen/`
- **Sync orquestrador 2 etapas:** `scripts/qwen-sync.py` (capture + reconcile)
- **Cobertura:** 115 chats / 3 projects / 4 project files capturados
- **Reconciler v3 (FEATURES_VERSION=2):** preservation completa convs + projects
- **Parser canonico v3** (`src/parsers/qwen.py` + `_qwen_helpers.py`):
  115 convs / 1.799 msgs / 9 tool_events / 133 branches / 3 projects /
  4 project_docs. Cobertura:
  - **8 chat_types** mapeados pra modes: chat (80) / search (19) /
    research (12, deep_research) / dalle (4, t2i+t2v)
  - **Branches via DAG plano** (`parentId`/`childrenIds` + `currentId`) —
    113 main + 20 secondary
  - **reasoning_content** → `Message.thinking` (raro nesta base — feature
    de modelos QwQ-style, condicional)
  - **search_results** (de blocks `info.search_results`) → ToolEvent
  - **t2i/t2v/artifacts** sempre emitem ToolEvent (image/video_generation, artifact)
  - **`pinned` → `is_pinned`** (cross-platform), **`archived` → `is_archived`**
  - **`meta.tags` + `feature_config`** preservados em `settings_json`
  - **content_list[*].timestamp** → `Message.start_timestamp`/`stop_timestamp`
  - **Project com `custom_instruction`** + `_files` (com presigned S3 URLs,
    expiram 6h) → `project_metadata` + `project_docs` parquets
- **Quarto descritivo** (`notebooks/qwen.qmd`): 17MB HTML, render < 30s,
  cor primaria roxo (#615CED)
- **Findings empiricos:** `docs/qwen-probe-findings-2026-05-01.md`
- **Tests:** 14 parser-specific (incluindo coverage dos 8 chat_types)
- **Auth:** profile copiado de `~/Desktop/AI Interaction Analysis/.storage/qwen-profile-default/`
- **Comandos:**
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/qwen-sync.py
  PYTHONPATH=. .venv/bin/python scripts/qwen-parse.py
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/qwen.qmd
  ```
- **TODO:** download local dos project files (presigned S3 expira 6h);
  validar cenarios CRUD (rename/delete/pin/archive) — bateria manual

**DeepSeek — ciclo completo end-to-end validado em 2026-05-01:**
- **Pasta unica cumulativa:** `data/raw/DeepSeek/` e `data/merged/DeepSeek/`
- **Sync orquestrador 2 etapas:** `scripts/deepseek-sync.py` (capture + reconcile)
- **Cobertura:** 79 chat_sessions capturadas
- **Reconciler v3 (FEATURES_VERSION=2):** sem projects (DeepSeek nao expoe)
- **Parser canonico v3** (`src/parsers/deepseek.py` + `_deepseek_helpers.py`):
  79 convs / 722 msgs / 20 tool_events / 271 branches. Cobertura:
  - **R1 reasoning** → `Message.thinking` (**222 msgs / 31% das msgs!**)
  - **`thinking_elapsed_secs`** sumarizado em `settings_json.thinking_elapsed_total_secs`
  - **`accumulated_token_usage`** → `Message.token_count` (98% cobertura)
  - **`pinned` → `is_pinned`** (cross-platform)
  - **`agent`** (chat/agent) + **`model_type`** (default/thinking) → `mode`
  - **`current_message_id`** + **`parent_id`** (int IDs) → branches DAG plano.
    79 main + **192 secundarias** (DeepSeek tem MUITO regenerate — 2.4 branches/conv)
  - **`search_results`** (estrutura rica com title/url/metadata) → ToolEvent +
    `Message.citations_json`
  - **`incomplete_message`** + **`status`** → `Message.finish_reason` (100% cob.)
  - **Files** per msg → `attachment_names`
- **Quarto descritivo** (`notebooks/deepseek.qmd`): 8MB HTML, cor azul royal
- **Findings empiricos:** `docs/deepseek-probe-findings-2026-05-01.md`
- **Tests:** 15 parser-specific
- **Schema antigo do legacy parser estava DESATUALIZADO** (esperava `mapping`
  + `fragments`, mas API atual retorna `chat_messages` flat com campos
  dedicados). Parser v3 eh rewrite total.
- **Auth:** profile copiado de `~/Desktop/AI Interaction Analysis/.storage/deepseek-profile-default/`
- **Comandos:**
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/deepseek-sync.py
  PYTHONPATH=. .venv/bin/python scripts/deepseek-parse.py
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/deepseek.qmd
  ```
- **TODO:** validar cenarios CRUD; testar agent mode (visto no schema mas
  nao capturado nesta base); R1 reasoner com `model_type='thinking'` validar
  comportamento

**Estado atual `data/merged/ChatGPT/chatgpt_merged.json`:**
- 1171 convs cumulativas (1168 active + 3 preserved_missing)
- E a fonte de verdade pro ChatGPT
- LAST_RECONCILE.md e reconcile_log.jsonl atualizados a cada run

**Parser canonico ChatGPT (Fase 2 do plan, validado em 2026-04-28):**
- `src/parsers/chatgpt.py` (`ChatGPTParser`, `source_name="chatgpt"`) — substitui
  o legacy GPT2Claude bookmarklet e o MVP `chatgpt_v2.py`
- Versoes anteriores em `_backup-temp/parser-v3-promocao-2026-04-28/` (gitignored,
  deletar quando confirmar que tudo OK)
- Output em `data/processed/ChatGPT/`: conversations.parquet, messages.parquet,
  tool_events.parquet, branches.parquet
- Cobertura: tree-walk completo (preserva branches off-path), voice (com
  direction in/out), DALL-E (em ToolEvent), uploads do user (em Message),
  tether_quote, canvas, deep_research, custom_gpt vs project distinction,
  preservation (is_preserved_missing, last_seen_in_server)
- Rodada validada: 1171 convs / 17583 msgs / 3109 tool_events / 1369 branches,
  idempotente byte-a-byte, 261 testes passando
- Plan formal: `docs/parser-v3-plan.md`
- Findings empiricos: `docs/parser-v3-empirical-findings.md`
- Validation v2 vs v3: `docs/parser-v3-validation.md`
- Comando: `PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py`

**Quarto descritivo ChatGPT (Fase 3.1 do dashboard, validado em 2026-04-28):**
- `notebooks/chatgpt.qmd` — data-profile "zero trato": schema + cobertura
  + amostras + distribuicoes + preservation. Sem sentiment/clustering/topic
  (analise interpretativa fica em `~/Desktop/AI Interaction Analysis/`)
- `notebooks/_style.css`, `notebooks/_quarto.yml` — config compartilhado
- Stack: DuckDB queryando parquets + Plotly + itables (tabela filtravel)
- Output: `notebooks/_output/chatgpt.html` (gitignored, ~52MB self-contained)
- Render: ~20s pras 1171 convs (criterio <30s)
- Briefing: `docs/quarto-briefing.md`
- Comando:
  ```bash
  # IMPORTANTE: Quarto precisa achar o python do venv (com duckdb, plotly, itables)
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
  ```
  Sem `QUARTO_PYTHON`, ele tenta usar python do system e falha por falta de deps.
  Pra Streamlit (Fase 3.2) integrar via `subprocess`, vai precisar setar essa env
  var antes de chamar `quarto render`.

## Pontos de verificacao por plataforma (cross-feature checks)

Quando descobrimos uma feature numa plataforma (pin, archive, voice, share),
**checar empiricamente nas outras** se ela tambem existe e se o extractor
captura. Lista crescente conforme aprendemos:

### Pin
- **Perplexity:** ✅ pin de **thread** (`list_pinned_ask_threads`, campo
  `is_pinned: true`). Schema canonico: `Conversation.is_pinned`. Validado
  2026-05-01.
- **ChatGPT:** ✅ pin de **conversation** + pin de **GPT (gizmo)** — duas
  features distintas, ambas existem.
  - **Conv:** campos `is_starred` e `pinned_time` no schema raw (UI: "Pin"
    no menu da conv). NAO existe endpoint dedicado tipo `/pinned` — vem
    no payload normal de `/conversations` e `/conversation/{id}`. Parser
    mapeia `is_starred` → `Conversation.is_pinned`. Validado 2026-05-01
    via probe Chrome MCP (initial probe foi enganoso porque `chatgpt_raw.json`
    antigo nao tinha nenhuma conv pinada).
  - **Gizmo:** endpoint `/backend-api/gizmos/pinned` retorna lista. Capturado
    em `data/raw/ChatGPT/gizmos_pinned.json` (sidecar separado).
- **Claude.ai:** ✅ tem `is_starred` (pin) + `is_temporary` no schema da API
  (`/api/organizations/{org}/chat_conversations_v2`, validado 2026-05-01 via
  probe Chrome MCP em 835 convs). Extractor extrai `is_starred` em discovery
  e preserva `is_temporary` no JSON cru. **Parser v3 mapeia ambos**:
  `is_starred` → `Conversation.is_pinned` (12 pinadas em 834 convs);
  `is_temporary` preservado in-place (0 capturadas — feature efemera).
  **Sem campo `is_archived`** no schema visivel.
- **Gemini, NotebookLM, Qwen, DeepSeek:** ⏸ verificar quando
  extractor for atualizado pra schema v3.

### Archive de thread/conv
- **Perplexity:** Enterprise-only. Backend aceita `archive_thread`/`unarchive_thread`
  mas estado nao expoe via API publica em conta Pro. Sem gap.
- **ChatGPT:** ✅ schema raw tem `is_archived` + `_archived`. UI tem opcao
  Archive. Atualmente 0 convs arquivadas em 1168 (feature funciona, so nao
  usada). **TODO:** quando user arquivar, validar reconciler + parser.
- **Outras:** verificar quando o extractor for refeito.

## Comportamento do servidor ChatGPT (validado empiricamente)

- **`update_time` em rename:** servidor BUMPA pra hora atual quando renomeias
  conv pela sidebar. Validado em 2026-04-28 com 2 chats antigos (out/2025 e
  mai/2025) — ambos saltaram pra 2026-04-28 ao renomear. Implicacao: caminho
  incremental normal (`update_time > cutoff`) ja pega rename. Guardrail no
  `_filter_incremental_targets` (compara title da discovery vs prev_raw) eh
  defesa em profundidade caso comportamento mude.
- **Rename de project (nome do project_id, nao IDs):** sempre detectado via
  `project_names` re-fetched a cada run. Independente de update_time.
- **`/projects` 404 intermitente:** caller tem fallback automatico para
  `/gizmos/discovery/mine` -> DOM scrape. Fail-fast cobre quando todos os
  fallbacks falham juntos (raro).

**O que NAO precisa ser feito (proposto e descartado em 27/abr):**
- Re-mergear "do zero" varrendo `_backup-gpt/merged-*` — reconciler ja faz
  preservation naturalmente, merged atual ja tem tudo
- Refatorar `asset_downloader.py` pra "pool cumulativo" — hardlink no sync
  resolve sem mexer no script
- Criar `chatgpt-reconcile-from-zero.py` ou similar — sync ja orquestra

**Antes de criar QUALQUER script novo:** conferir se sync, scripts standalone
existentes ou os helpers em src/ ja resolvem. Se nao tiver certeza, ler
codigo + memory antes de propor.

## Princípios inegociaveis (decisoes ja tomadas — nao questionar sem motivo forte)

### 1. Capturar uma vez, nunca rebaixar
- Binarios (assets, project_sources) sao precious — alguns nao podem ser
  refetched (asset removed do servidor)
- `chatgpt-sync.py` etapa 2 hardlinka binarios antigos pro raw novo ANTES
  de chamar download. Download script ve hardlinks como existing e pula
- Mover essa estrutura para outras plataformas

### 2. Preservation acima de tudo
- Convs deletadas no servidor: `preserved_missing` no merged (reconciler)
- Sources removidas no servidor: `_preserved_missing: true` no `_files.json`
  do project (preservation no `project_sources.py`)
- Mesmo padrao para outras plataformas

### 3. Fail-fast contra discovery flakey
- Discovery do ChatGPT eventualmente 404a `/projects` e cai pra DOM scrape parcial
- Sem protecao, raw fica com 800 convs em vez de 1166 — proxima run ve
  300+ convs como "novas" e refetcha tudo
- `_get_max_known_discovery` varre `data/raw/` recursivo (inclui subpastas
  tipo `_backup-gpt/`) pra ter baseline robusto
- Threshold 20%: se discovery atual < 80% do maior historico, **aborta antes
  do fetch** com mensagem clara
- Aplicar mesmo padrao em todos os extractors (#19 do backlog)

### 4. Schema canonico e fronteira
- `src/schema/models.py` define `Conversation`, `Message`, `ToolEvent`,
  `ConversationProject`, `Branch`
- Extractors entregam raw/merged JSON; **parsers** entregam parquet nesse
  schema (atualmente so ChatGPT — outras 6 plataformas em backlog)
- Analise (em outro projeto, `~/Desktop/AI Interaction Analysis/`) consome
  parquet read-only

## Estrutura

```
src/
├── extractors/<source>/      # 6 modulos por plataforma (auth, api_client,
│                             # discovery, fetcher, asset_downloader, orchestrator)
├── reconcilers/<source>.py   # build_plan + run_reconciliation, preserva missing
├── parsers/                  # merged -> parquet (canonico)
│   ├── chatgpt.py            # ⭐ canonico (Fase 2 done) — tree-walk, branches,
│   │                         #    ToolEvents, voice, DALL-E, custom_gpt etc
│   ├── _chatgpt_helpers.py   # helpers puros do parser ChatGPT
│   └── <outras>.py           # legacy / parsers de outras plataformas (backlog)
└── schema/models.py          # Conversation, Message, ToolEvent, Branch, ConversationProject

scripts/
├── <source>-login.py         # 1x por plataforma, abre navegador pra login
├── <source>-export.py        # captura conversas (incremental por default)
├── <source>-reconcile.py     # standalone (sync ja chama)
├── <source>-download-assets.py
├── <source>-download-project-sources.py  (so ChatGPT por enquanto)
├── chatgpt-sync.py           # ⭐ orquestrador 5 etapas, modelo pras outras
└── chatgpt-parse.py          # ⭐ merged -> parquet canonico (Fase 2)

notebooks/
├── _quarto.yml               # config compartilhado (output_dir, format html)
├── _style.css                # CSS compartilhado (cor ChatGPT, tabelas, plotly)
├── chatgpt.qmd               # ⭐ data-profile descritivo (Fase 3.1)
└── _output/                  # (gitignored) HTML rendirizado

tests/  (260+ testes — TODOS devem passar antes de qualquer merge)
data/
├── raw/                      # (gitignored) saida dos extractors
├── merged/                   # (gitignored) saida dos reconcilers
└── processed/                # (gitignored) saida dos parsers
.venv/                        # local — Python 3.14, criado em 2026-04-27
                              # setup: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Helpers chave (NAO mexer sem entender)

### `src/extractors/chatgpt/orchestrator.py`
- `_find_last_capture(raw_root)`: ordena por `run_started_at` (NAO por mtime).
  Robusto contra cenario "pasta sem sufixo + pasta com sufixo de hora".
- `_get_max_known_discovery(raw_root)`: rglob recursivo pra incluir backups.
- `DISCOVERY_DROP_ABORT_THRESHOLD = 0.20`

### `scripts/chatgpt-sync.py`
- `hardlink_existing_binaries(target)`: rglob recursivo, mais recente por
  mtime, hardlink (cross-fs vira copia automatica), pula existing no target.

### `src/extractors/chatgpt/project_sources.py`
- `_merge_with_preserved(current, index_path)`: merge cumulativo do indice
  `_files.json`, marca removidas com `_preserved_missing`.

## Comandos comuns

Pre-requisito: `.venv` ativado (`source .venv/bin/activate`) ou usar `.venv/bin/python` direto.

```bash
# Smoke test imports
PYTHONPATH=. .venv/bin/python -c "from src.extractors.chatgpt.orchestrator import run_capture; print('ok')"

# Rodar testes do ChatGPT
PYTHONPATH=. .venv/bin/pytest tests/extractors/chatgpt/ tests/test_chatgpt_sync.py -v

# Sync ChatGPT completo (rapido se tem captura anterior)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-sync.py --no-voice-pass

# Parse merged -> parquet canonico (idempotente; ~3s pras 1171 convs atuais)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py

# Renderiza o data-profile descritivo (~20s)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
```

## Convencoes do projeto (heranca do projeto antigo)

- Commits via `~/.claude/scripts/commit.sh "mensagem"` (forca autor Marlon Lemes,
  bloqueia Co-Authored-By)
- Conventional commits em portugues (feat:, fix:, chore:, docs:, refactor:, test:)
- `data/raw/` gitignored — dados pessoais nunca no repo
- Idioma codigo: ingles. Comentarios e docs: portugues sem acentos preferencialmente

## Headless vs headed por plataforma

Heranca do AI Interaction Analysis (projeto antigo). **Login eh sempre
headed (1x por conta, persiste em `.storage/<plat>-profile-<conta>/`).**
**Captura difere por plataforma:**

| Plataforma | Login | Captura |
|---|---|---|
| Claude.ai | headed (1x) | headless ✅ |
| Gemini | headed (1x) | headless ✅ |
| NotebookLM | headed (1x) | headless ✅ |
| Qwen | headed (1x) | headless ✅ |
| DeepSeek | headed (1x) | headless ✅ |
| ChatGPT | headed (1x) | **headed** (Cloudflare detecta headless) |
| Perplexity | headed (1x) | **headed** (Cloudflare 403 em headless) |

5 das 7 rodam headless por padrao. ChatGPT e Perplexity precisam abrir
browser na captura — Cloudflare bloqueia headless com 403 / challenge
"Just a moment...". Documentado por design em `perplexity/api_client.py:12-13`.

**Implicacao operacional:** se rodar Claude/Gemini/NotebookLM/Qwen/DeepSeek
e ver browser abrir, **algo esta errado**. Se for ChatGPT ou Perplexity,
**esperado**.

Ver tambem `docs/glossary.md` pra terminologia (discovery vs merged vs
baseline, preserved_missing, fail-fast, hardlink, etc).

## Gotchas conhecidos

- `chatgpt-export.py` roda `headless=False` no orchestrator (DOM scrape de
  projects + voice pass + Cloudflare). `download-assets.py` roda `headless=True`
  (so chama API com cookies, nao precisa de DOM)
- 8 assets ChatGPT confirmados como **irrecuperaveis** (parents deletados no
  servidor) — failed=8 em download-assets eh esperado, nao bug
- DOM scrape de projects as vezes pega 40 em vez de 47 — fail-fast cobre
- Discovery `/projects` 404a as vezes — fail-fast cobre via fallback
  `/gizmos/discovery/mine` -> DOM scrape
