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

## Status (2026-05-03)

| Plataforma | Capture | Reconcile | Sync orquestrador | Parser canonico | Quarto descritivo | Notas |
|---|---|---|---|---|---|---|
| ChatGPT | ✅ | ✅ | ✅ (4 etapas, pasta unica) | ✅ (Fase 2 done) | ✅ (Fase 3.1 done) | Preservation completa, rename detection, fail-fast, parser cobrindo branches + ToolEvents, data-profile renderizando |
| Claude.ai | ✅ | ✅ | ✅ (3 etapas, pasta unica) | ✅ v3 | ✅ | thinking, tool_use/result+MCP, branches via parent_uuid, is_pinned/is_temporary mapeados, 24k msgs / 16k events |
| Qwen | ✅ | ✅ | ✅ (3 etapas, pasta unica) | ✅ v3 | ✅ | shipped (3/4 CRUD validados em 2026-05-01; archive eh no-op upstream Pro/free, nao gap) |
| DeepSeek | ✅ | ✅ | ✅ (2 etapas, pasta unica) | ✅ v3 | ✅ | shipped (3/3 CRUD validados em 2026-05-01) |
| Gemini | ✅ | ✅ | ✅ (3 etapas multi-conta) | ✅ v3 | ✅ | shipped (4/4 CRUD validados em 2026-05-02; share eh URL upstream-only, nao gap). 47+33=80 convs / 560 msgs / 889 tool_events / 215 imgs / ~18 Deep Research. 8 modelos. Pin descoberto via probe em `c[2]` do listing MaZiqc |
| NotebookLM | ✅ | ✅ | ✅ | ✅ | ✅ | **shipped 2026-05-02** (multi-conta acc-1+acc-2; 143 conversations / 138 messages / 1174 sources / 1174 source_guides / 389 outputs / 9 parquets total; bateria CRUD validada — pin nao existe upstream). **+ account-3 legacy more.design** (shipped 2026-05-03): 11 notebooks / 33 msgs / 27 outputs / 6 briefs via parser legacy `src/parsers/manual/notebooklm_legacy_more_design.py`, `capture_method='legacy_notebooklm_more_design'`, qmd `notebooks/notebooklm-legacy.qmd`, snapshot raw em `data/external/notebooklm-snapshots/more-design-2026-03-30/` |
| Perplexity | ✅ | ✅ | ✅ | ✅ | ✅ | Auditoria + reconciler + parser v3 + Quarto. 82 conversations (78 threads + 4 pages), 9 artifacts c/ binarios, 1 orphan, 4 spaces |

**CLI (3 fontes adicionais — dado local em vez de captura web):**

| CLI | Source | Copy script | Parser v3 | Status |
|---|---|---|---|---|
| Claude Code | claude_code | ✅ `cli-copy.py --source claude_code` | ✅ shipped 2026-05-03 | 3742 convs / 136k msgs / 78k tool_events / 3742 branches; cross-val 1:1 vs pai = v3 ⊇ pai (+271 msgs, +6k tool_events) |
| Codex | codex | ✅ `cli-copy.py --source codex` | ✅ shipped 2026-05-03 | 112 convs / 2.6k msgs / 6.1k tool_events / 112 branches; cross-val 1:1 = EXATO match com pai |
| Gemini CLI | gemini_cli | ✅ `cli-copy.py --source gemini_cli` | ✅ shipped 2026-05-03 | 12 convs / 181 msgs / 84 tool_events / 12 branches; cross-val 1:1 = +2 convs vs pai (v3 capta extras) |

**Manual saves (parser via `scripts/manual-saves-sync.py` — re-mapeiam source pra plataforma original):**

| Parser | source destino | capture_method | Convs |
|---|---|---|---|
| `clippings_obsidian` | chatgpt (20), claude_ai (1) | `manual_clipping_obsidian` | 21 |
| `copypaste_web` | chatgpt (1), claude_ai (1), gemini (2), qwen (1) | `manual_copypaste` | 5 |
| `terminal_claude_code` | claude_code (3) | `manual_terminal_cc` | 3 |

Total: 29 convs / 403 msgs / 70 tool_events. Output em `<source>_manual_<table>.parquet`
em cada `data/processed/<Plataforma>/`. Quartos fazem UNION via
`setup_views_with_manual()` em `src/parsers/quarto_helpers.py`.

**Schema v3.2 (2026-05-03):** `Conversation.capture_method` (default `'extractor'`,
manuais sobrescrevem). Permite distinguir extractor vs manual-saves vs futuras
fontes externas no mesmo parquet via UNION.

**External preservado (`data/external/`, ~2.0GB total — sem parser canônico):**

| Categoria | Tamanho | Conteudo |
|---|---|---|
| `manual-saves/` | 1.8MB | Inputs ativos pros 3 parsers manuais (parsavel) |
| `openai-gdpr-export/{2026-03-27,2026-04-27}/` + `_archive/2026-04-27.zip` | 1.0GB | Exports GDPR oficiais OpenAI |
| `chatgpt-extension-snapshot/2026-03-27/` | 51MB | conversations.json + memories.md + instructions.json |
| `claude-ai-snapshots/{2026-03-26,2026-03-30,2026-04-18}/` | 360MB | snapshots brutos pre-extractor |
| `deepseek-snapshots/2026-03-27/` | 3.2MB | conversations.json + user.json (UI export pre-extractor) |
| `deep-research-md/` | 208KB | 2 .md exportados manualmente (nao parsado — design adiado) |
| `notebooklm-snapshots/more-design-2026-03-30/` | 594MB | Captura legacy da conta extinta (parsed via parser legacy → account-3) |
| `perplexity-orphan-threads/` | 56KB | 1 thread Perplexity deletada do servidor antes do canonico assumir |

Todos preservados como blob. README em `data/external/README.md`.
Padrao: snapshots via UI das plataformas vão pra `<plat>-snapshots/<date>/`,
mantendo arquivos originais (ver `memory/project_snapshots_via_ui.md`).

## Limpeza de raws concluida em 2026-05-03 — pai vazio

Sessao de housekeeping fechou ~24GB de cleanup distribuidos em 5 fases:

- **Fase 1:** filho `data/raw/<Plat> Data/` (5 pastas legacy) — 144M
- **Fase 2:** pai `.storage/` (profiles antigos) — 535M
- **Fase 3:** pai legacy ja migrado pra `data/external/` (Claude/ChatGPT snapshots, Manual Saves, exports) — 643M
- **Fase 4:** pai `data/raw/NotebookLM Data/more.design/` (594M) → snapshot + parser legacy + qmd + UNION
- **Fase 5:** pai `data/raw/*` inteiro (22GB) — cross-val rigoroso (rglob recursivo) confirmou zero gaps

**Resultado:** pai foi de 25G → 4.4G. Filho 11G (cresceu com 1323 sessoes Claude Code recuperadas + snapshot more.design).

Cross-val final (rodada extra com `rglob` apos descobrir bug iterdir no v1):

| Plataforma | Legacy / Canonico | Status |
|---|---|---|
| ChatGPT | 1162 / 1171 | ✅ 0 missing |
| Claude.ai | 829 / 835 | ✅ 0 missing |
| Qwen | 112 / 115 | ✅ 0 missing |
| DeepSeek | 78 / 79 | ✅ 0 missing |
| Gemini | 80 / 80 | ✅ 0 missing |
| NotebookLM | 136 / 143 | ✅ 0 missing (mais 11 account-3 legacy) |
| Claude Code | 4152 / 4625 | ✅ 0 missing (1323 sessoes legacy migradas) |
| Codex | 105 / 113 | ✅ 0 missing |
| Gemini CLI | 14 / 16 | ✅ 0 missing (1 sessao migrada) |
| Perplexity | 78 / 78 | ✅ 0 missing (orphan em external) |

Migracoes feitas durante a limpeza:
- 1323 sessoes Claude Code legacy → canonico (workspaces que sumiram do `~/.claude/projects/`)
- 1 sessao Gemini CLI legacy → canonico
- DeepSeek UI snapshot → `data/external/deepseek-snapshots/2026-03-27/`
- Perplexity orphan thread (CV evaluation) → `data/external/perplexity-orphan-threads/`
- more.design NotebookLM → `data/external/notebooklm-snapshots/` + parser legacy + account-3

## TODOs com probe pendente (exigem session live)

Não bloqueiam captura básica — são gaps de cobertura adicional que precisam
de probe com dado real:

- `src/extractors/chatgpt/dom_voice.py:21` — Pass 2 voice DOM seletores.
  Voice msgs já são detectadas no Pass 1 (raw heuristic) — Pass 2 adicionaria
  texto transcribed. Precisa: ChatGPT logado + voice conv + inspect.
- `src/parsers/_notebooklm_helpers.py:148` — `extract_chat_turns` retorna
  `[]` quando `chat_raw` não-None (schema posicional desconhecido).
  Empírico: 371 arquivos chat raw, **0 com conteúdo não-null** — TODO é
  defensivo. Precisa: notebook com chat populado.
- `src/parsers/_notebooklm_helpers.py:290` — `extract_mind_map_tree`
  serializa metadata cru. Tree completa de nodes não mapeada. Precisa:
  probe Chrome MCP por RPC alternativo.
- `src/parsers/gemini.py:24` — Search/grounding citations não extraídas
  de `tool_events` (event_type='search' registrado, mas citations
  internas não estruturadas). Precisa: probe Gemini com Search ativo.

Quando atacar: abrir uma sessão dedicada com browser/Chrome MCP + plataforma
logada, probar e atualizar parser.

## Backlog principal

1. **`notebooks/00-overview.qmd`** — visao consolidada cross-plataforma via
   DuckDB UNION ALL. Pickup brief em `memory/project_pickup_brief_cross_platform.md`.
2. **DVC pipeline filho ↔ pai** (decorrente da limpeza) — filho versiona
   canonicos via DVC, pai consome via `dvc import-url`. Pickup brief em
   `memory/project_pickup_brief_dvc_pipeline.md`. Fase 6 da limpeza
   (delete `processed/`/`unified/` no pai) é consequencia natural disso.
3. **Pos-shipping:** publicacao opensource (sanitizar credenciais,
   README, exemplos).

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
- Findings empiricos em `docs/platforms/perplexity/audit-findings.md`.
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
- **Parser canonico v3** (`src/parsers/perplexity.py`): 82 conversations
  (~41 copilot + ~37 concise + 4 research/pages), 374 messages, 2312 tool_events
  (2134 search_result + 168 media_reference + 9 asset_generation), 81 branches.
  Pages tem `conversation_id='page:<slug>'`. Search results extraidos de
  `blocks[*].web_result_block.web_results`. Idempotente (~1s pra rodar).
- **Quarto descritivo** (`notebooks/perplexity.qmd`): 22MB HTML self-contained
- **Findings empiricos:** `docs/platforms/perplexity/audit-findings.md`
- **Journey + dificuldades:** `docs/platforms/perplexity/journey-2026-05-01.md`
  (10 licoes transferiveis pras outras 5 plataformas)
- **Validacoes pendentes:** `docs/platforms/perplexity/pending-validations.md`
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
- **Findings empiricos:** `docs/platforms/claude-ai/parser-empirical-findings.md`
- **Validation cruzada vs legacy:** `docs/platforms/claude-ai/parser-validation.md`
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
- **Findings empiricos:** `docs/platforms/qwen/probe-findings-2026-05-01.md`
- **Tests:** 14 parser-specific (incluindo coverage dos 8 chat_types)
- **Auth:** profile copiado de `~/Desktop/AI Interaction Analysis/.storage/qwen-profile-default/`
- **Comandos:**
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/qwen-sync.py
  PYTHONPATH=. .venv/bin/python scripts/qwen-parse.py
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/qwen.qmd
  ```
- **Asset download integrado** (`scripts/qwen-download-assets.py`):
  326 URLs detectadas em msgs/projects, 321 baixadas com sucesso,
  196MB local. Parser resolve `asset_paths` via `assets_manifest.json`:
  171 msgs com `asset_paths` populados.
- **STATUS: SHIPPED em 2026-05-01.** Bateria CRUD validada:
  - ✅ **Rename** (chat 8c97d9ab → "Codemarker V2 from mqda"): title bate em
    parquet, `updated_at` bumpa pra 2026-05-02
  - ✅ **Pin** (chat 240ac30f "Meta-Analytics Explained"): `is_pinned=True`,
    `updated_at` bumpa
  - ⚠️ **Archive** (chat 75924b8e "Empathy Map Analysis"): no-op observavel
    upstream — servidor aceita request (`updated_at` bumpa) mas flag `archived`
    nunca persiste, endpoint `/v2/chats/archived` retorna `len=0`, todos os
    listings ainda incluem o chat. Mesmo padrao do Perplexity Enterprise-only.
    **NAO eh gap do extractor** — schema canonico tem `is_archived`, so nunca
    True em Pro/free. Probe: `scripts/qwen-probe-archived.py`
  - ✅ **Delete** (chat 2d7e6a81 "Future Tech Innovations"):
    `is_preserved_missing=True`, `last_seen_in_server` preserva 2026-04-30
- **3 bugs descobertos+fixados durante bateria** (`docs/platforms/qwen/server-behavior.md`):
  1. `_get_max_known_discovery(output_dir.parent)` vazava entre plataformas
     (1171 ChatGPT, 835 Claude.ai sendo usados como baseline do Qwen) — fix
     em qwen/deepseek/claude_ai/chatgpt orchestrators
  2. `discover()` persistia `discovery_ids.json` antes do fail-fast — proxima
     run perdia janela de refetch — fix: separar `discover()` de
     `persist_discovery()` em qwen + deepseek
  3. `--full` nos sync scripts nao propagava pro reconciler (extractor
     refetchava bodies novos, reconciler usava cache stale) — fix em
     qwen-sync.py + deepseek-sync.py + claude-sync.py

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
- **Findings empiricos:** `docs/platforms/deepseek/probe-findings-2026-05-01.md`
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
- **`model_type='expert'` mapeado** pra mode='research' (R1 reasoner)
- **`status` enum descoberto:** `FINISHED`/`INCOMPLETE`/`WIP` (716/5/1 msgs)
- **`feedback`/`tips`/`ban_edit`/`ban_regenerate`/`thinking_elapsed_secs`**
  preservados em `Message.attachments_json` (220 msgs com metadata)
- **STATUS: SHIPPED em 2026-05-01.** Bateria CRUD 3/3 validada:
  - ✅ **Rename** (chat 1d4823f1 "Meta Analytics Explained" → "Meta Analytics
    Explicado"): title bate em parquet, `updated_at` bumpa pra 2026-05-02
  - ✅ **Pin** (chat 37ca105e "Data Governance vs Research Operations:
    Qualidade de Dados"): `is_pinned=True`, `updated_at` bumpa
  - ✅ **Delete** (chat a7087bd3 "Olá, eu tenho uma planilha no go"):
    `is_preserved_missing=True`, `last_seen_in_server` preserva 2026-04-30,
    title preservado
- DeepSeek tambem se beneficiou dos bugs descobertos durante bateria do Qwen
  (mesma cadeia de orchestrators). Bug 2 fix preventivo aplicado antes da
  bateria — sync rodou limpo na primeira tentativa: discovered=78, fetched=2
  (rename+pin), reused=76, preserved=1 (delete).

**Gemini — ciclo completo end-to-end validado em 2026-05-02:**
- **Multi-conta** — primeira plataforma com 2 contas Google (`hello.marlonlemes@gmail.com`
  e `marloonlemes@gmail.com`). Profiles em `.storage/gemini-profile-{1,2}/`.
- **Pasta unica cumulativa per-account:**
  `data/raw/Gemini/account-{N}/` e `data/merged/Gemini/account-{N}/`
- **Sync orquestrador 3 etapas multi-conta** (`scripts/gemini-sync.py`):
  capture per-account + assets + reconcile per-account. Itera ambas contas em
  sequencia (default) ou `--account N` pra rodar so uma.
- **Cobertura:** 47 + 33 = 80 convs / 560 msgs / 889 tool_events / 215 imagens
  baixadas (lh3.googleusercontent.com) + 18 Deep Research markdown reports
  extraidos
- **Reconciler v3** (`FEATURES_VERSION=2`): preservation per-account,
  idempotente, output em pasta unica cumulativa
- **Parser canonico v3** (`src/parsers/gemini.py` + `_gemini_helpers.py`):
  schema raw eh **posicional** (Google batchexecute, sem keys) — caminhos
  descobertos via probe (`scripts/gemini-probe-schema.py`):
  - `turn[2][0][0]` → user text
  - `turn[3][0][0][1]` → assistant text (chunks)
  - `turn[3][21]` → model name (e.g. '2.5 Flash', '3 Pro', 'Nano Banana')
  - `turn[3][0][0][37+]` → thinking blocks (heuristica >=200 chars excl. main response)
  - `turn[4][0]` → timestamp epoch secs
  - 8 modelos detectados (2.5 Flash 118 msgs, 3 Pro 81, Nano Banana 33,
    3 Flash Thinking 21, etc)
  - **41% das assistant msgs com thinking** (116/280)
  - Image generation via regex sobre JSON do turn → ToolEvent +
    `Message.asset_paths` resolvidos via `assets_manifest.json` per-account
  - Multi-conta com namespace `account-{N}_{uuid}` em `conversation_id`
- **Bateria CRUD UI 4/4 validada:**
  - ✅ **Rename** (chat dc5c683537a19cd1 → "Benchmarks Smiles Gol Pesqusias"):
    title bate em parquet
  - ✅ **Pin** (chat 98c60a18de056385 "Análise de Dados da Cota Parlamentar"):
    `is_pinned=True`. **Pin descoberto via probe** — campo `c[2]` do listing
    MaZiqc retorna `True` quando pinado, `None` senao
  - ✅ **Delete** (chat b17426c13c5e1bc3): `is_preserved_missing=True`,
    title + last_seen preservados
  - ✅ **Share URL** (`gemini.google.com/share/c2a6a6436942`): confirmado
    upstream-only — servidor gera URL publica isolada, NAO modifica body do
    chat nem campos do listing. Nao eh gap do extractor
- **Quarto descritivo:** 3 documentos
  - `notebooks/gemini-acc-1.qmd` (template canonico, account-1 only)
  - `notebooks/gemini-acc-2.qmd` (template canonico, account-2 only)
  - `notebooks/gemini.qmd` (consolidado, com stacked bars por conta nas
    secoes-chave: timeline, top models, msgs assistant, distribuicao de tamanho)
  - Cor: azul Google `#4285F4` (acc-1), azul mais escuro `#1A73E8` (acc-2)
- **Bugs descobertos+fixados durante migracao+bateria** (todos preventivos
  aplicados em qwen/deepseek/claude_ai/chatgpt orchestrators):
  1. `_get_max_known_discovery(output_dir)` (nao `parent`)
  2. `discover()` lazy persist (separado de `persist_discovery()`)
  3. `--full` propagado pro reconcile
  4. `fetch_conversations(skip_existing=False)` quando orchestrator ja filtrou
  5. Discovery captura `pinned` do `c[2]` do MaZiqc + reconciler detecta
     `pinned_changed` como signal de update
- **Dashboard adaptado:** `_collect_logs()` agora suporta multi-account
  (`base/account-*/<log>.jsonl`); `conversations_parquet_path` aceita
  ambas convencoes (`<source>_conversations.parquet` ou `conversations.parquet`)
- **Findings empiricos:** `docs/platforms/gemini/server-behavior.md`
- **Probes:** `scripts/gemini-probe-schema.py`, `scripts/gemini-probe-pin-share.py`
- **Auth:** profiles copiados de `~/Desktop/AI Interaction Analysis/.storage/gemini-profile-{1,2}/`
- **Captura HEADLESS** (sem Cloudflare em runtime)
- **Comandos:**
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py             # ambas contas
  PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py --account 1 # so conta 1
  PYTHONPATH=. .venv/bin/python scripts/gemini-parse.py
  for f in gemini gemini-acc-1 gemini-acc-2; do
    QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/${f}.qmd
  done
  ```

**NotebookLM — ciclo completo end-to-end validado em 2026-05-02:**
- **Multi-conta** — segunda plataforma com 2 contas (acc-1 = en, acc-2 = pt-BR).
  Profiles em `.storage/notebooklm-profile-{1,2}/`. NotebookLM nao eh chat
  puro: cada notebook gera ate 9 tipos de outputs (audio, blog, video,
  flashcards, quiz, data table, slide deck PDF+PPTX, infographic, mind map).
- **Pasta unica cumulativa per-account:** `data/raw/NotebookLM/account-{N}/`
  e `data/merged/NotebookLM/account-{N}/`
- **Sync orquestrador 3 etapas multi-conta** (`scripts/notebooklm-sync.py`):
  capture per-account + assets + reconcile per-account. Itera ambas contas
  em sequencia (default) ou `--account N` pra rodar so uma. Tempos: acc-1
  = 79min (95 nb, 1.2GB raw + 1484 assets); acc-2 = 26min (48 nb).
- **Cobertura full sync:**
  - acc-1: 95 notebooks / 974 sources / 1484 assets (4 audios + 12 videos
    + 30 slide decks + 1344 page images + 54 text artifacts + 76 notes
    + 45 mind_maps)
  - acc-2: 48 notebooks / 199 sources / 38 assets + 96 notes + 53 mind_maps
  - Total: 962M+263M raw + 977M+310M merged ≈ 2.5GB
- **RPCs mapeados** (api_client + fetcher):
  - `wXbhsf` list, `rLM1Ne` metadata, `VfAZjd` guide,
    `khqZz` chat (None na maioria), `cFji9` notes,
    `gArtLc` artifacts (9 tipos), `v9rmvd` artifact content individual
    (types 2/4/7/9 — gap-fill descoberto), `CYK0Xb` mind_map tree
    (payload `[nb_uuid, mm_uuid]` descoberto via probe — bug fixado),
    `hPTbtc` mind_map UUID, `hizoJc` source content
- **Reconciler v3** (FEATURES_VERSION=2): preservation completa per-account,
  pasta unica cumulativa (sem subpastas dated), `LAST_RECONCILE.md` +
  `reconcile_log.jsonl` per-account
- **Parser canonico v3** (`src/parsers/notebooklm.py` + `_notebooklm_helpers.py`):
  rewrite total. **8 parquets** (4 canonicos + 4 auxiliares):
  - canonicos: 143 conversations / 121 messages / 0 tool_events / 143 branches
  - auxiliares: 1173 sources (com content extraido, reusa `ProjectDoc`) /
    277 notes (kind ∈ {note, brief}) / 389 outputs (cobre 8 dos 9 tipos +
    mind_map=10) / 363 guide_questions
  - **Decisao chave:** `guide.summary` vira system message (sequence=0) em
    notebooks que tem guide — garante `message_count >= 1`. 22/143 (15%)
    notebooks nao tem guide (vazios/Untitled/recem-criados) — sem system
    msg, mas branch/conversation continuam
  - 12 tests parser-specific cobrindo 8 parquets + idempotencia + system msg
- **Quarto descritivo** (3 docs, cor laranja Google `#F4B400`):
  - `notebooks/notebooklm.qmd` (consolidado, stacked bars per-account)
  - `notebooks/notebooklm-acc-1.qmd` (template canonico, account-1 only)
  - `notebooks/notebooklm-acc-2.qmd` (template canonico, account-2 only)
  - 12MB acc-1, 12MB acc-2, 7.6MB consolidado. Render < 30s cada
- **Findings empiricos:** `docs/platforms/notebooklm/probe-findings-2026-05-02.md`
- **Spec design:** `docs/superpowers/specs/2026-05-02-notebooklm-schema-design.md`
- **Plan implementacao:** `docs/superpowers/plans/2026-05-02-notebooklm-implementation.md`
- **Bugs fixados durante migracao:**
  1. CYK0Xb payload errado — retornava None silenciosamente. Probe revelou
     `[nb_uuid, mm_uuid]` ao invés de `[mm_uuid]`. Mind map tree agora capturado.
  2. `_extract_mind_map_uuid` lendo do RPC errado (cFji9 ao invés de hPTbtc).
- **5 bugs preventivos aplicados desde primeiro commit** (das 5 plataformas
  anteriores): _get_max_known_discovery(output_dir) nao parent, discover()
  lazy persist, --full propagado, fetch_conversations skip_existing=False,
  pasta unica per-account com namespace `account-{N}_{uuid}`
- **Dashboard:** suporte pros qmds per-account adicionado em
  `dashboard/quarto.py` + `dashboard/pages/platform.py`. Multi-conta agora
  mostra 3 links por plataforma (consolidado + per-account)
- **Bateria CRUD UI validada** (2026-05-02 via app mobile):
  - ✅ Rename ("Heatmap Studies" → "Heatmap estudos") — title bate em parquet
  - ✅ Delete ("Westward Mushrooms") — `is_preserved_missing=True`,
    `last_seen_in_server` preservado, title preservado
  - ✅ Add source — sources.parquet acc-1 = 974 → 975
  - ✅ Pin: **NotebookLM nao tem feature de pin** (confirmado no app)
  - **Achado empirico:** `update_time` do listing eh VOLATIL — 93/94 notebooks
    bumped entre 2 syncs sem mudanca real (servidor reindexa periodicamente
    + acesso ao notebook bumpa). Reconciler usa hash semantico, nao timestamp,
    pra decidir refetch — comportamento ja mitigado por design.
  - Detalhes: `docs/platforms/notebooklm/server-behavior.md`
- **Source-level summary + tags + questions capturados** (gap fechado em
  2026-05-02): RPC `tr032e` descoberto via probe Chrome MCP +
  Playwright headed (click manual no source). Payload empirico
  `[[[[source_uuid]]]]`. Implementado `fetch_source_guide` no api_client +
  fetcher salvando em `sources/{uuid}_guide.json`. Schema canonico expandido
  com `NotebookLMSourceGuide` dataclass + tabela auxiliar
  `notebooklm_source_guides.parquet` — **9 parquets** total (era 8).
  Cobertura: 1174/1173 sources com summary (1 source duplicado entre
  notebooks). Cada guide tem ~800-1000 chars summary + 5 tags + 3 questions
  geradas pelo modelo.
- **Comandos:**
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py             # ambas contas
  PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py --account 1 # so conta 1
  PYTHONPATH=. .venv/bin/python scripts/notebooklm-parse.py
  for f in notebooklm notebooklm-acc-1 notebooklm-acc-2; do
    QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/${f}.qmd
  done
  ```

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
- Plan formal: `docs/parser-v3/plan.md`
- Findings empiricos: `docs/parser-v3/empirical-findings.md`
- Validation v2 vs v3: `docs/parser-v3/validation.md`
- Comando: `PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py`

**Quarto descritivo ChatGPT (Fase 3.1 do dashboard, validado em 2026-04-28):**
- `notebooks/chatgpt.qmd` — data-profile "zero trato": schema + cobertura
  + amostras + distribuicoes + preservation. Sem sentiment/clustering/topic
  (analise interpretativa fica em `~/Desktop/AI Interaction Analysis/`)
- `notebooks/_style.css`, `notebooks/_quarto.yml` — config compartilhado
- Stack: DuckDB queryando parquets + Plotly + itables (tabela filtravel)
- Output: `notebooks/_output/chatgpt.html` (gitignored, ~52MB self-contained)
- Render: ~20s pras 1171 convs (criterio <30s)
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
- Refatorar `asset_downloader.py` pra "pool cumulativo" — pasta unica
  cumulativa + `skip_existing` resolve sem mexer no script
- Criar `chatgpt-reconcile-from-zero.py` ou similar — sync ja orquestra

**Antes de criar QUALQUER script novo:** conferir se sync, scripts standalone
existentes ou os helpers em src/ ja resolvem. Se nao tiver certeza, ler
codigo + memory antes de propor.

## Princípios inegociaveis (decisoes ja tomadas — nao questionar sem motivo forte)

### 1. Capturar uma vez, nunca rebaixar
- Binarios (assets, project_sources) sao precious — alguns nao podem ser
  refetched (asset removed do servidor)
- Pasta unica cumulativa (`data/raw/<Source>/` mesma a cada run, sem timestamp)
  + `skip_existing` nos downloaders garante que binarios ja capturados nao
  sao re-baixados nem perdidos
- Mesmo padrao replicado nas outras plataformas (claude_ai/perplexity/qwen/
  deepseek/gemini)

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
├── _quarto.yml               # config compartilhado (toc lateral, embed, theme)
├── _style.css                # CSS compartilhado
├── _template.qmd             # ⭐ partial universal (1.x schema/sample + 2.x cobertura
│                             #    + 3.x volumes/distrib + 4.x preservation)
├── _template_aux.qmd         # ⭐ partial pras tabelas auxiliares (NotebookLM 5,
│                             #    Qwen/Claude.ai project_metadata+docs)
├── chatgpt.qmd, claude-ai.qmd, codex.qmd, ...  # ~50 linhas cada — config (SOURCE_KEY,
│                             #    SOURCE_TITLE, SOURCE_COLOR, AUX_TABLES, ACCOUNT_FILTER) +
│                             #    {{< include _template.qmd >}}. 14 qmds no total.
└── _output/                  # (gitignored) HTML rendirizado, ~40MB cada

tests/  (514 testes — TODOS devem passar antes de qualquer merge)
data/
├── raw/                      # (gitignored) saida dos extractors
├── merged/                   # (gitignored) saida dos reconcilers
├── processed/                # (gitignored) saida dos parsers (per-source)
└── unified/                  # (gitignored) saida do unify-parquets.py (cross-platform)
.venv/                        # local — Python 3.14, criado em 2026-04-27
                              # setup: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Overview cross-platform (2026-05-04)

`data/unified/` materializa 11 parquets consolidados a partir de
`data/processed/<Source>/`. Concat + dedup PK composta. Idempotente.
Rodar via `scripts/unify-parquets.py` apos os parses individuais
(`<plat>-parse.py`). Output: `data/unified/{conversations, messages,
tool_events, branches, sources, notes, outputs, guide_questions,
source_guides, project_metadata, project_docs}.parquet`.

**Quarto overview** le `data/unified/` direto:
- `notebooks/_template_overview.qmd` — body cross-platform (484L,
  9 secoes: comparativo plat × metricas, timeline stacked, modelos
  cross, capture_method, tool events, words, preservation, lifetime,
  itable filtravel)
- `notebooks/00-overview.qmd` — todas as 10 sources (sem filtro)
- `notebooks/00-overview-web.qmd` — 6 web (chatgpt, claude_ai,
  perplexity, qwen, deepseek, gemini)
- `notebooks/00-overview-cli.qmd` — 3 CLIs (claude_code, codex,
  gemini_cli)
- `notebooks/00-overview-rag.qmd` — NotebookLM

Per-subset qmd tem ~50L (setup + `SOURCES_FILTER = [...]` + include
do template). Helper `setup_unified_views(con, unified_dir,
sources_filter)` em `quarto_helpers.py` carrega views DuckDB com
filtro opcional `WHERE source IN (...)`.

```bash
PYTHONPATH=. .venv/bin/python scripts/unify-parquets.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-web.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-cli.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-rag.qmd
```

**Decisao arquitetural:** filho materializa `data/unified/` (interface
DVC pro consumer + overview qmds). Decorrente da decisao "filho eh
casa canonica" (memory `project_canonical_data_home.md`). Consumer vai
ler via `dvc import-url` (pipeline DVC futura).

**Testes:** `tests/test_unify_parquets.py` (18 testes — identify_table,
source_from_path, dedup PK composta, idempotencia, schema divergente
UNION BY NAME, enriquecimento source).

## Template canonico de notebooks (2026-05-03)

14 qmds compartilham `notebooks/_template.qmd` (~900L) + opcionalmente
`notebooks/_template_aux.qmd` (~200L pra plataformas com aux tables).
Cada per-source qmd tem ~50 linhas — so config + include do template.

**Helpers compartilhados:** `src/parsers/quarto_helpers.py` (1 modulo, 11
funcoes — setup de views, schema/query, formatters, plot). Importado pelos
14 qmds.

**Sections universais (template):**
- 1.1-1.4 schema + sample por tabela canonica (conv/msg/tool/branch)
- 2.1 capture_method breakdown (extractor vs manual saves) — schema v3.2
- 2.2-2.5 cobertura (model/thinking/tokens/latencia)
- 3.1 timeline + cumulativo
- 3.2 activity heatmap (hora x dia)
- 3.3-3.4 msgs/words user vs assistant
- 3.5-3.6 tool events + success rate + duration (CLIs)
- 3.7-3.10 top models/longest/size/lifetime (`updated_at - created_at`)
- 3.11 branches forks
- 3.12 account breakdown (multi-conta)
- 4.1-4.3 preservation/states/itable filtravel
- 5.x auxiliares (NotebookLM/Qwen/Claude.ai) — quando AUX_TABLES set

**Sections conditional via `has_col()`:** mostradas so quando a plataforma
tem o campo. Ex: `summary` (Claude.ai), `citations_json` (Claude.ai/Perplexity),
`thinking` (mostra mesmo quando 0 — informativo), `interaction_type`
(`human_ai` vs `ai_ai` em CLIs), `account` (Gemini/NotebookLM multi-conta).

**Per-account filter:** `ACCOUNT_FILTER = "1"` no per-source qmd recria
views lendo direto dos parquets com `WHERE account = 'X'` — evita recursao
no DuckDB binder. Usado por `gemini-acc-{1,2}.qmd`, `notebooklm-acc-{1,2}.qmd`,
`notebooklm-legacy.qmd`.

**40 testes unitarios** em `tests/parsers/test_quarto_helpers.py` cobrem:
fmt_pct/fmt_int/safe_int (incluindo regressao NaN), has_col/has_view/
table_count, setup_views_with_manual (extractor only, manual only, UNION,
schema divergente capture_method), setup_notebook (sem/com filter,
regressao recursao, SQL injection safe, aux tables).

**Adicionar uma secao nova:** mexer no `_template.qmd` (1 lugar) — aparece
nos 14 qmds automaticamente. Adicionar campo conditional: usar `has_col(con,
table, col)` como guarda.

**Render:** `QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render
notebooks/<plat>.qmd`. Sem `QUARTO_PYTHON`, falha por dep do .venv.

## Helpers chave (NAO mexer sem entender)

### `src/extractors/chatgpt/orchestrator.py`
- `_find_last_capture(raw_root)`: ordena por `run_started_at` (NAO por mtime).
  Robusto contra cenario "pasta sem sufixo + pasta com sufixo de hora".
- `_get_max_known_discovery(raw_root)`: rglob recursivo pra incluir backups.
- `DISCOVERY_DROP_ABORT_THRESHOLD = 0.20`

### `scripts/chatgpt-sync.py`
- Orquestra capture + assets + project_sources + reconcile em sequencia.
  Como a pasta `data/raw/ChatGPT/` eh cumulativa (mesma pasta a cada run,
  sem timestamp), os downloaders pulam binarios ja existentes via
  `skip_existing` — nao precisa mais de hardlink entre runs como na
  arquitetura legada de subpastas datadas.

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

# Renderiza o data-profile descritivo (~20-60s, conforme volume)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd

# Testes do template canonico de notebooks (40 testes, < 1s)
PYTHONPATH=. .venv/bin/pytest tests/parsers/test_quarto_helpers.py -v

# Suite completa
PYTHONPATH=. .venv/bin/pytest tests/  # 514 testes, ~3s
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
