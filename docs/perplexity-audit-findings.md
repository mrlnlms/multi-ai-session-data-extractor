# Perplexity — auditoria empirica do extractor (2026-04-29)

Investigacao motivada por gaps suspeitos no extractor (igual o caso de
voice messages do ChatGPT, que so foram descobertas via auditoria de
dados reais). Profile do projeto pai (78MB, 24/abr) reusado pra
captura aqui.

Probes rodados:
- `scripts/perplexity-probe-features.py` — network tap nas secoes
  Library / Spaces / Computer / History / Scheduled
- `scripts/perplexity-probe-spaces.py` — drill-down em Spaces individuais

## Estado da captura inicial (2026-04-29)

```
Raw: data/raw/Perplexity Data/2026-04-29T16-32/
Threads: 78 (mesmo nº da última captura no projeto pai, 24/abr)
Errors: 0
Warning: HTTP 400 em pinned threads (silenciosamente perdido)
```

## Gaps identificados

### 1. Bug pinned threads — HTTP 400 (resolvido)

**Sintoma:** `api_client.py:62-68` chama `list_pinned_ask_threads`
via `_fetch(path)` (default GET) e ignora o erro com warn:
```
warn: pinned failed: HTTP 400 on GET /rest/thread/list_pinned_ask_threads...
```

**Causa:** endpoint exige `POST` (igual `list_ask_threads`). GET retorna
400 com qualquer query string. POST com body `{}` retorna 200.

**Probe:**
```
GET   ?version=2.18&source=default        -> 400
POST  ?version=2.18&source=default {}     -> 200 ✓
POST  ?version=2.18&source=default {full} -> 200 ✓
GET   ?version=2.19, 2.20, sem version    -> 400
```

**Fix:** `_fetch(path, method="POST", body={})` em `list_pinned_threads`.

---

### 2. Spaces (collections) — feature inteira ausente do extractor

Perplexity tem **Spaces** (na sidebar) — internamente chamados
**collections** na API. Sao colecoes de threads + files + metadata
(description, instructions, suggested_queries, primers, etc).

**Conta atual tem 4 spaces:**
| Title | UUID prefix | Thread count visivel | Files |
|---|---|---|---|
| Bookmarks (default) | f572ce20 | 1+ | 0 |
| GAS | 75e5df63 | ? | 0 |
| Heatmaps | 8c756721 | ? | 0 |
| Brainstorm Buddy | dcde2f19 | ? | 0 |

(`thread_count` no metadata global retorna 0 mas `list_collection_threads`
retorna threads — bug do servidor / stat estale.)

**Endpoints reais (descobertos via network tap, nao chute):**

| Endpoint | Metodo | Funcao |
|---|---|---|
| `/rest/collections/list_user_collections` | GET | Lista todas as collections do user |
| `/rest/collections/get_collection?collection_slug=<slug>` | GET | Metadata de 1 collection |
| `/rest/collections/list_collection_threads?collection_slug=<slug>&limit=20&filter_by_user=false` | GET | Threads dentro da collection |
| `/rest/spaces/{uuid}/pins/threads?include_assets=true` | GET | Threads pinned no space (vazio na conta) |
| `/rest/spaces/{uuid}/tasks` | GET | Tasks Computer no space (vazio na conta) |
| `/rest/file-repository/list-files` | POST | Files do space (body com `file_repository_type: COLLECTION, owner_id: <uuid>`) |

**Endpoints chutados que retornaram 404** (nao usar):
`/rest/collections/{uuid}`, `/rest/collections/{uuid}/threads`,
`/rest/spaces/{uuid}`, `/rest/spaces/info/{uuid}`. **Importante:** API
usa `collection_slug` em query, NAO uuid em path.

**Schema `collection` (resposta de `get_collection`):**
```
uuid, title, description, instructions, suggested_queries,
visual_concepts, emoji, slug, s3_social_preview_url,
access, user_permission, space_type, thread_count, page_count, file_count,
owner_user, contributor_users, max_contributors,
model_selection, template_id, focused_web_config (link_configs),
enable_web_by_default, primers,
is_pinned, is_invited, pending_join_request_status
```

`description`, `instructions`, `suggested_queries`, `primers`,
`model_selection`, `focused_web_config` sao **conteudo de configuracao
do user** que se perde hoje.

---

### 3. Threads dentro de Spaces — overlap com list_ask_threads

**Pergunta:** as threads que aparecem em `list_collection_threads` sao
as MESMAS do `list_ask_threads`, ou sao paralelas/perdidas?

**Validacao empirica pos re-capture (2026-04-29):**

| Space | Threads em space | Em list_ask_threads | Orphans |
|---|---|---|---|
| Bookmarks | 4 | 4 | 0 |
| GAS | 1 | 0 | **1** |
| Heatmaps | 2 | 2 | 0 |
| Brainstorm Buddy | 0 | 0 | 0 |
| **Total** | 7 | 6 | **1** |

**Achado: 1 thread orphan.**
- UUID `d344c501-46aa-4951-85f7-6d27d2d4631d`
- Title: "There is a possibility to program for Google Apps Script using VSCode..."
- mode=concise, last_query_datetime=2024-09-02
- Em GAS space, **NAO esta no list_ask_threads**
- `fetch_thread` retorna **HTTP 400 ENTRY_NOT_FOUND** — foi deletada do servidor

**Implicacao critica:** `list_collection_threads` preserva refs ate de
threads deletadas (uuid + title + last_query_datetime + mode). E uma
fonte de **preservation passiva** que o extractor antigo nunca explorava.
Mesmo sem fetchar o body, ja temos metadata.

**NAO e cap temporal:**
- Mais antiga em list_ask_threads: 2024-08-23
- Orphan da GAS: 2024-09-02 (depois!)
- Distribuicao das 78: 2024 (42), 2025 (30), 2026 (6)
- Filtro do list_ask_threads parece ser presenca-no-servidor, nao data.

**Mapping thread↔space agora preservado** em
`spaces/{uuid}/threads_index.json`.

---

### 4. Computer / Scheduled / History — sem entidade nova capturavel (conta free)

**Computer (section [computer] no probe):**
- `thread/list_gallery_threads` — galeria publica showcase, **nao do user**
- `workflows` — templates oficiais, **nao do user**
- `tasks/shortcuts/mentions` — presets oficiais, **nao do user**
- `homepage-widgets/computer/primers`, `onboarding/computer` — UI/onboarding state
- `billing/credits*` — 404 (esperado, conta free)
- Threads do Computer **do user** (com `mode=asi`): captura via `list_ask_threads`
  filtrada — JA cobertas no extractor atual

**History (section [history]):**
- Apenas `event/analytics`. View UI sem endpoint REST proprio.

**Scheduled (section [scheduled]):**
- Apenas `event/analytics` e `visitor/consent-requirement`. URL
  `/scheduled` provavelmente redireciona — botao no canto superior
  abre popover, nao navega. **Nao mapeado neste probe** (precisaria
  click no botao real).

**Conclusao:** Nenhuma entidade nova precisa ser adicionada ao
extractor pra Computer/Scheduled/History em conta free. Threads do
user ja sao captados.

**TODO:** quando alguem com conta Pro testar, validar:
- `/rest/billing/credits/balance` retorna saldo? (relevante pra
  tracking, nao pra captura conversacional)
- Endpoints proprios de `tasks/list` (nao apenas mentions)?
- `/scheduled` clicando no botao real (nao URL) — provavel popover
  com endpoint proprio

---

## Status de implementacao (2026-04-29)

### ✅ Fase 1 — pinned bug — DONE
`api_client.py:list_pinned_threads` agora usa POST com body `{}`.
Confirmado via re-capture: sem warning de pinned.

### ✅ Fase 2 — Spaces no extractor — DONE
- `api_client.py`: 4 metodos novos
  (`list_user_collections`, `get_collection`, `list_collection_threads`,
  `list_collection_files`) + helper `list_all_collection_threads` paginado.
- `src/extractors/perplexity/spaces.py`: novo modulo (`discover_spaces` +
  `fetch_spaces`).
- `orchestrator.py`: chama spaces apos threads, atualiza capture_log.
- Output em `spaces/_index.json` + `spaces/{uuid}/{metadata,threads_index,files}.json`.

### ✅ Fase 3 — Re-capture validada — DONE
2026-04-29T16-47:
- 78 threads (78 reusadas incremental)
- 4 spaces (Bookmarks 4, GAS 1, Heatmaps 2, Brainstorm Buddy 0)
- 0 erros, sem warning pinned
- 1 orphan detectado em GAS

### ⏸ Open question — orphan handling
Como tratar a thread orphan (existe em space mas deletada do servidor)?
Opcoes:
- (A) Manter como esta — `threads_index.json` do space ja preserva uuid+
  metadata. Parser canonico (Fase 5 do plan replicacao) pode comparar
  com tabela de threads e marcar como `is_orphan_in_space`.
- (B) Adicionar logica explicita no orchestrator: tentar fetch das
  threads em space ausentes do list_ask_threads, marcar erros como
  `_orphan_preserved=true` em algum index dedicado.

**Recomendacao:** opcao A — sem novo codigo. Threads_index dos spaces
ja tem tudo que precisa. Parser cobre a diferenca.

### ✅ Comportamento do servidor (validado empiricamente 2026-05-01)

Testes manuais via UI + capture:
- **Rename de thread**: servidor BUMPA `last_query_datetime` pra hora atual.
  Validado: thread `a3a6d563` antes 2025-06-27, depois rename 2026-05-01T14:58.
  Foi pro topo da lista.
  → **Reconciler detecta via caminho incremental normal** (igual ChatGPT).
- **Add to space**: thread aparece em `list_collection_threads` do space alvo.
  Validado: thread `83887374` adicionada a Brainstorm Buddy via dialog
  "Choose Space".
- **Delete via menu thread (Library)**: backend retorna `ENTRY_DELETED`
  ao tentar fetchar. Thread some de **tudo** — `list_ask_threads` + qualquer
  `list_collection_threads`. Validado com thread `83887374`.
- **Delete legacy** (caso `d344c501`): thread deletada do servidor mas
  **continua referenciada** em `list_collection_threads` da GAS.
  Discrepancia vs caso `83887374`: ambos retornam `ENTRY_DELETED` ao fetch,
  mas so um vira orphan no space. **Hipotese:** depende de quando foi
  deletada vs quando foi adicionada ao space (sequencia temporal); ou de
  qual UI exata foi usada (menu da thread em library vs dentro do space).
  Nao deterministico no curto teste.
  → **Reconciler precisa cobrir AMBOS os cenarios:**
  - Thread some do list_ask_threads E do space → marca como deletada
  - Thread some do list_ask_threads MAS continua em list_collection_threads
    → marca como `_orphan_in_space` no threads_index do space

### ⏸ Fase 4 — reconciler de Spaces (depois)
`src/reconcilers/perplexity.py` precisa estender pra reconciliar tambem
`spaces/_index.json` (preservation analoga a project_sources do ChatGPT)
+ marcar orphans em `threads_index.json` baseado em diff com captured.

Logica do reconciler:
1. **Threads** (sempre):
   - Diff `list_ask_threads` atual vs anterior
   - `_preserved_missing` pra threads que sumiram do listing
2. **Spaces** (novo):
   - Diff `_index.json` atual vs anterior
   - Spaces que sumiram → marca preserved (o user deletou o space)
3. **Threads em spaces** (novo):
   - Pra cada space, diff `threads_index.json` atual vs anterior
   - Threads que sumiram do space MAS estao em `list_ask_threads` →
     foram removidas do space (sem deletar)
   - Threads que sumiram do space MAS NAO estao em `list_ask_threads` →
     orphan (caso CV) ou deletadas. Sub-diff:
     - `fetch_thread()` retorna `ENTRY_DELETED` → deletada de vez
     - Caso contrario → preserved/orphan
4. **Pages e Files**: idem, preservation se sumiram

### ⏸ Fase 5 — sync orquestrador (depois)
`scripts/perplexity-sync.py` (3 etapas: capture + assets + reconcile) +
pasta unica cumulativa `data/raw/Perplexity/` (sem espaco no nome).

---

## Out of scope (nao fazer agora)

- Pages do Perplexity (apareceu na lista de features mas endpoint
  proprio nao surgiu nos probes; provavel feature Pro)
- `thread/list_recent` — duplica info de list_ask_threads
- Reconcile de Spaces — Fase 4
- Sync orquestrador — Fase 5
- Pasta unica — Fase 5
