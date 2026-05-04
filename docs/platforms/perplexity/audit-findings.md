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

### ✅ Bateria UI 2026-05-01 (Bloco A das pending-validations)

User com **conta Pro** (`display_model: pplx_pro_upgraded`) executou 7 das 8
acoes do Bloco A (1.6 GDrive dropado por redundancia). Sync rodou em ~80s.
Resultados por acao:

| # | Acao | UUID | Validado? | Achado |
|---|---|---|---|---|
| 1.1 | Voice em thread existente | `a3a6d563` | 🟡 parcial | `last_query_datetime` bumpou (14:58 → 17:36); **`query_str` veio como TEXTO normal** — servidor transcreve e descarta audio. Sem campo `is_voice` no schema. **Nao capturavel.** |
| 1.2 | Share (anyone with link → private) | `0ffebdcb` | 🟡 limitado | Schema **nao mudou** — `privacy_state: NONE`, `read_write_token` igual, `thread_url_slug` igual. Limitacao da nossa metodologia: capturamos so o estado FINAL (private). UI mostra 3 niveis: Private / Specific people / Anyone with the link. |
| 1.3 | Rename Space | `8c756721` | ✅ | title "Heatmaps" → "Heatmaps Study", slug bumpou tambem (`heatmaps-...` → `heatmaps-study-...`), `updated_datetime` bumpou de 2024-11-09 → 2026-05-01T18:00. **Resolve item 3.4 das limitacoes upstream (era TODO).** |
| 1.4 | Deletar Space | `75e5df63` (GAS) | ✅ | Antes do delete, thread movida pra Bookmarks. Reconciler marcou GAS com `_preserved_missing: true` no merged `_index.json`. Pasta fisica preservada. |
| 1.5 | Pin thread | `d20e2c86` | ❌ | `list_pinned_ask_threads` retornou `[]` mesmo com pin feito no UI. Sem `is_pinned`/`bookmark_state=PINNED` no body da thread (`bookmark_state: NOT_BOOKMARKED`). **Pin em library usa endpoint diferente do `list_pinned_ask_threads`** (que provavelmente cobre apenas pin em spaces). **GAP do extractor.** |
| 1.6 | GDrive connector | — | ❌ dropado | Redundante com upload direto de file em space (1.7) |
| 1.7 | Heatmaps Study — file + instructions + link + skill | `8c756721` | 🟡 4/5 capturado | **Capturado:** description, instructions ricas, suggested_queries (12 auto-geradas), focused_web_config.link_configs (uxcam.com), primers (1 RESEARCH com 3 queries), file (Heat Maps `.md`, 67KB). **NAO capturado:** skill upload. Extractor nao chama endpoint de skills. **GAP do extractor.** |
| 1.8 | Mover thread Bookmarks → Brainstorm Buddy | `4cec8783` | ✅ | Reconciler marcou: 1 removida-sem-delete do Bookmarks. Thread aparece em `threads_index.json` do Brainstorm Buddy. |

### ❗ Achados emergentes desta bateria

**1. Bumps de `updated_datetime` em spaces (alem de rename):**
- Mover thread pra/de space tambem bumpa: Bookmarks "2025-04-12" → "2026-05-01T18:01",
  Brainstorm Buddy "2026-05-01T14:54" → "2026-05-01T17:40".
- Implicacao: `_index.json` por si so e fonte de verdade pra detectar
  mudancas em space. Reconciler ja faz diff field-by-field.

**2. UI "Archive" em /library:**
- Threads em `/library` tem menu (⋯) com Pin / Rename / Add to Space / **Archive** / Delete.
- Sidebar de history so tem Rename / Delete.
- Action "Archive" nao mapeada — pode ter endpoint proprio
  (`/rest/thread/archive` ou similar). **Probe pendente.**

**3. UI Share (3 niveis confirmados):**
- Private (default) — `privacy_state: NONE` no schema
- Specific people (invite) — schema desconhecido
- Anyone with the link — schema desconhecido
- **Nao conseguimos validar mutacoes** porque metodologia incremental
  captura so o estado AGORA. Pra validar, precisaria capturar baseline
  ANTES do toggle e diff DEPOIS. Workaround: anotar o estado ANTES de
  mudar no UI, anotar o link gerado, comparar manualmente.

**4. Rename de space muda o slug:**
- "heatmaps-jHVnIaPPSxSLNrU6uEF9iQ" → "heatmaps-study-jHVnIaPPSxSLNrU6uEF9iQ"
- Sufixo (UUID-like) preservado, prefixo segue title.
- Implicacao: `slug` nao e identificador estavel. Sempre usar `uuid`
  como chave.

**5. Conta Pro tem display_model `pplx_pro_upgraded`:**
- Threads novas saem com `display_model: pplx_pro_upgraded`,
  `user_selected_model: pplx_pro`.
- Permite distinguir threads criadas em Pro vs versoes free anteriores.
- **Implicacao no parser:** mapeamento de mode pode precisar ajuste se
  Pro introduzir modes novos (`mode=ASI` etc).

### ✅ Gaps fechados via probe direto na sessao Chrome (2026-05-01)

Probe rodando JS dentro do Chrome do user (`window.fetch` autenticado),
testando candidatos de endpoint sem precisar de UI clicks.

#### 1. Pin de thread em library — RESOLVIDO

**Bug:** `list_all_threads` em `api_client.py` mantinha `seen` set e
ignorava a versao da thread vinda de `list_pinned_ask_threads` quando
ela ja aparecia em `list_ask_threads`. So que **`list_pinned_ask_threads`
retorna a thread COM campo extra `is_pinned: true`** que nao existe no
listing principal — e esse campo era descartado.

**Fix:** mudou `seen: set` para `seen: dict[str, dict]`, e ao processar
pinned, faz `update()` na thread existente pra propagar `is_pinned`
(e qualquer outro campo extra). Validado: thread `d20e2c86` agora aparece
em `threads-index.json` com `is_pinned: true`.

#### 2. Skills em spaces — RESOLVIDO

**Endpoints descobertos (probe direto):**
- `GET /rest/skills?scope=collection&scope_id=<UUID>` — skills de 1 collection
- `GET /rest/skills?scope=individual` — skills do user fora de collection
- `GET /rest/skills?scope=global` — 10 built-ins do Perplexity (skill library)
- `GET /rest/skills?scope=organization` — vazio em conta nao-Enterprise
- **Schema:** `id, name, description, file_url (S3 signed URL),
  scope, created_at, updated_at, tags, enabled`
- 404 com `error_code=MISSING_COLLECTION_SCOPE_ID` se faltar `scope_id`
- Scopes validos enum: `'global', 'organization', 'collection', 'individual'`

**Implementacao:** `list_collection_skills(uuid)` e `list_user_skills()`
no api_client. Saida em `spaces/{uuid}/skills.json` e `user/skills.json`.
Validado: 1 skill `heatmap-explainer` capturado em Heatmaps Study com
schema completo.

**Nota sobre `file_url`:** S3 signed URL com expiracao curta (15min).
Schema do SKILL.md (YAML frontmatter `name` lowercase+hyphens 1-64 chars
+ `description` com trigger phrases + body markdown) esta no
`/rest/skills` POST com body `{scope, file: <multipart>}`.

#### 3. Action "Archive" de thread — RESOLVIDO (Enterprise-only, no-op pra Pro)

**Endpoints descobertos:**
- `POST /rest/thread/archive_thread` body `{context_uuid: <UUID>}` → retorna `{"status":"success"}`
- `DELETE /rest/thread/unarchive_thread/<context_uuid>` → retorna `{"status":"success"}`

**Comportamento bizarro descoberto via teste empirico (2026-05-01):**

Testamos archive numa conta Pro. Resultado:
1. Backend ACEITA o request (200 success)
2. Mas `list_ask_threads` retorna a thread **igual** apos archive (nao some)
3. `fetch_thread` retorna JSON **byte-a-byte identico** apos archive
   (zero diff em thread_metadata, zero diff em entries)
4. Nenhum campo `is_archived`, `archived_at`, ou `thread_status='archived'`
   aparece em qualquer lugar
5. Filtros candidatos (`with_archived`, `archived_only`, `view: archived`,
   etc) sao todos ignorados pelo `list_ask_threads`

**Pista decisiva:** ao clicar Archive no UI da conta Pro, o frontend tenta
carregar `restricted-feature-loader-CeE8XF0f.js` que redireciona pra
`perplexity-ai.cloudflareaccess.com` (Cloudflare Access — zero-trust auth).
Chunk eh **gated Enterprise**. CORS bloqueia o chunk pra contas nao-Enterprise,
e o handler do Archive nunca executa direito — UI optimistic mostra "Archived"
e instantes depois faz rollback ("indo e voltando").

**Conclusao definitiva:** archive eh feature **Enterprise-only**. Pra contas
Pro/Free, e cosmetica e backend nao expoe estado archivado via endpoints
publicos. **Sem gap pro extractor:** threads arquivadas em Pro continuam
visiveis em todos os endpoints normais como qualquer thread.

**Endpoint de listagem de archived NAO descoberto** — provavelmente existe
mas so eh chamado pelo chunk restricted (Enterprise-only). Pra mapear:
contributor com conta Enterprise faz archive + intercepta XHRs. Documentado
como TODO Enterprise (analogo aos outros features Pro Max do doc
`pending-validations.md`).

#### 4. Voice em Perplexity — limitacao upstream confirmada

Servidor transcreve audio e salva apenas `query_str` (texto). Sem campo
de voice no schema — `is_voice`/`audio_url`/`transcription_meta` nao
existem. Analogo ao caso 3.1 (S3 attachments expirados): nao-bug, eh
comportamento upstream irrecuperavel.

### ⏸ TODOs persistentes

1. **Listar archived threads (Enterprise-only)** — confirmado via teste
   empirico que archive em conta Pro nao expoe estado via endpoints
   publicos. Pra mapear listagem: contributor Enterprise testa.
   **Sem urgencia** — em Pro, archive eh no-op observavel.

2. **Validar mutacao de `privacy_state` em share** — metodologia
   incremental nao captura toggle. Pra validar, precisaria 2 capturas
   intercaladas com mudanca no UI. Baixa prioridade (sabemos os 3
   niveis: Private / Specific people / Anyone with link).

3. **Validar list_pinned_ask_threads em conta sem Pro** — confirmado
   funcionar em Pro (`d20e2c86` capturada). Em conta free a feature
   pode nem existir no UI (item 1.5 da batiera anterior usou conta Pro).

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
