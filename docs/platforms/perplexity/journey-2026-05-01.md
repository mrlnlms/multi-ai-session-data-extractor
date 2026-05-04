# Perplexity — journey 2026-04-29 a 2026-05-01

Histórico do trabalho de nivelar Perplexity ao padrão do ChatGPT.
Documenta dificuldades enfrentadas e soluções pra que as 5 plataformas
restantes (Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek) possam
aproveitar essas lições.

## Resultado final — equiparação ChatGPT vs Perplexity

| Item | ChatGPT (2026-04-28) | Perplexity (2026-05-01) |
|---|---|---|
| Auth + profile persistente | ✅ headed (1x) | ✅ (reusou profile do projeto pai) |
| Captura headed | ✅ (Cloudflare) | ✅ (Cloudflare) |
| Pasta única cumulativa | ✅ `data/raw/ChatGPT/` | ✅ `data/raw/Perplexity/` |
| Sync orquestrador | ✅ 4 etapas | ✅ 2 etapas (Perplexity captura tudo num shot) |
| Reconciler | ✅ preservation completa | ✅ preservation + orphans + ENTRY_DELETED |
| Parser canônico v3 | ✅ | ✅ |
| Quarto descritivo | ✅ chatgpt.qmd | ✅ perplexity.qmd |
| Fail-fast discovery | ✅ DISCOVERY_DROP_ABORT_THRESHOLD | ✅ DROP_THRESHOLD reconciler |
| Idempotência | ✅ | ✅ |
| CRUD scenarios validados | 6 | 3 (rename / add-to-space / delete) |
| Volume real | 1171 conversations | 81 conversations |
| Testes | 261 | 6 (parser-specific) + 261 herdados |

**Status: equiparados em todas as dimensões funcionais.** Diferenças
são por volume real da conta e features específicas (Perplexity tem
Pages e Artifacts próprios; ChatGPT tem branches off-path e voice).

---

## Diferenças estruturais entre ChatGPT e Perplexity

| Aspecto | ChatGPT | Perplexity |
|---|---|---|
| Branches | mapping tree (off-path branches preservadas) | linear (1 branch por conv) |
| Projects/Spaces | "projects" com sources | "spaces" com threads + pages + files |
| Conteúdo gerado | DALL-E images, code interpreter | Artifacts (CODE_FILE/CHART/GENERATED_IMAGE) |
| Voice | in/out direction | mic existe (não testado) |
| GPTs custom | sim (custom_gpt) | não |
| Pages publicáveis | não | sim (UI Pages = API article) |
| Sources em conv | tools (web_search) | blocks[*].web_result_block.web_results |
| Multi-conta | sim | sim (mas não testamos) |

---

## Dificuldades enfrentadas (em ordem cronológica)

### 1. Esqueci de checar o projeto pai pelos profiles
**Sintoma:** sugeri rodar `perplexity-login.py` do zero. Usuário cortou:
"perai porra.. olha lá antes de criar do zero aqui por favor".

**Lição:** sempre checar `~/Desktop/AI Interaction Analysis/.storage/`
antes de propor login novo. Profile copiado funciona via fallback legacy
do `auth.py` (sufixo `-default` opcional).

**Permanente:** documentado em `CLAUDE.md` (seção "Projeto pai") e
`memory/feedback_check_parent_project_first.md`. Não cair de novo.

### 2. Schema escondido — UI vs API name divergence
**Sintoma:** UI mostra "Spaces", "Pages", "Artifacts" — API usa
nomes diferentes (`collections`, `articles`, `assets`).

| UI | API | Endpoint |
|---|---|---|
| Spaces | collections | `/rest/collections/list_user_collections` |
| Pages | articles | `/rest/article/{slug}` |
| Artifacts | assets | `/rest/assets/` |

**Lição:** **probe network-tap antes de chutar nomes**. Probes
diretos com `/rest/artifacts/list` etc retornaram 404. Só descobri
via Playwright com `page.on("response")` capturando XHRs reais
durante navegação manual.

### 3. Pinned threads — endpoint exigia POST, não GET
**Sintoma:** `list_pinned_ask_threads` retornava `HTTP 400` silenciosamente
(legacy fazia warn e seguia). Era bug do extractor — o endpoint mudou
ou sempre exigiu POST com body `{}`.

**Solução:** probe testou 7 variações (GET/POST × versões do API),
descobriu que `POST {body: {}}` retorna 200. Fix: 1 linha.

### 4. Pages SSR-only — slugs só aparecem após click
**Sintoma:** os 4 page titles do Bookmarks aparecem no HTML inicial
(`Brain Stores Memories...`), mas os **slugs** (necessários pra fetch
via `/rest/article/{slug}`) **não estavam em lugar nenhum** —
nem em `<a href>`, nem em `__NEXT_DATA__`, nem em scripts inline.

**Causa:** Perplexity é SPA Vite com router programático
(`router.push` no onClick), não tem `<a href>` literal pra pages.

**Solução:** **DOM-click scrape**:
1. Encontra row pelo SVG icon `#pplx-icon-custom-perplexity-page`
2. `row.click()` programaticamente
3. `expect_navigation()` + read URL após estabilizar
4. Extrai slug da URL `/page/{slug}`
5. `go_back()` ou `goto(space_url)` pra próxima

**Custo:** ~10s por page (lento mas confiável). Pra Bookmarks com
4 pages OK; pra spaces com 100+ pages, ficaria lento.

**Bug do scrape:** URL aparecia truncada inicialmente
(`microplastics-found-in-human-b-br1yKSQzT` em vez de `...br1yKSQzT_W4M0NkS4iADA`).
Fix: aguardar estabilização lendo `page.url` em loop até parar de mudar.
Também regex `[a-zA-Z0-9\-]` faltava `_` no hash — expandido pra `[a-zA-Z0-9\-_]`.

### 5. Conta free bloqueia features visíveis
**Sintoma:** ícones de Computer/Scheduled/Skills/Links/Deep Research
no UI, mas todos retornam 404 ou modal "Upgrade to Pro".

**Lição:** features Pro **podem aparecer no DOM mas não retornar dado**
em conta free. Não significa bug do extractor — é limitação de conta.
Documentar como **TODO: testar com conta Pro futura**.

### 6. Sources reais não estavam em `entry.sources`
**Sintoma:** parser inicial extraía 0 search_results. `sources` no
entry tem schema `{sources: ["web", "academic", ...]}` (lista de
strings de **categorias**, não dados).

**Solução:** sources reais ficam em `blocks[*].web_result_block.web_results`
— estrutura aninhada que só descobri varrendo blocks recursivamente.
Resultado: 0 → 2134 search_result tool_events.

### 7. Refresh URL endpoint mudou schema
**Sintoma:** legacy `_refresh_url_via_api` enviava `{url: "..."}` e
retornava 422 — `Field required: thread_id`.

**Causa:** schema da Perplexity API foi atualizado em algum momento.
Endpoint agora exige `thread_id` no body além da URL. Variantes:
- `/rest/file-repository/download-attachment` ⇒ `{url, thread_id}`
- `/rest/file-repository/download` ⇒ `{file_url, thread_id}` (campo "file_url" em vez de "url")

**Solução:** parser de attachments tenta as 4 combinações de payload.

### 8. Files antigos foram deletados upstream
**Sintoma:** mesmo com refresh URL OK, download retorna `404 NoSuchKey`
no S3. 6 attachments antigos (2024-2025) irrecuperáveis.

**Causa:** Perplexity faz cleanup automático de uploads antigos no S3.

**Solução:** manifest preserva entries com `status: "failed_upstream_deleted"`
pra **idempotência em re-runs** (skip ao invés de re-tentar). Mesmo
padrão dos 8 assets irrecuperáveis do ChatGPT.

### 9. Reconciler — bug de lookup do discovery
**Sintoma:** rodar reconciler 2x reportava `added=77` mesmo na 2ª vez
(deveria ser `copied=77` por idempotência).

**Causa:** `_load_discovery` procurava `discovery_ids.json` (nome do raw)
mas o merged salva como `threads_discovery.json`. Lookup falhava silenciosamente
no diretório merged.

**Solução:** `_load_discovery` agora tenta ambos os nomes em ordem.

### 10. CRUD scenarios divergentes (delete vs orphan)
**Sintoma empírico:** dois casos de "delete" comportam diferente:
- Caso A (`83887374`): renomeei + add-to-space + delete via menu →
  servidor retorna `ENTRY_DELETED`, thread some do listing global E
  do `list_collection_threads` do space.
- Caso B (`d344c501` legacy): delete antigo, retorna `ENTRY_DELETED`
  ao fetch, MAS continua referenciada em `list_collection_threads` da GAS.

**Hipótese:** pode ser timing (cleanup no servidor não roda
imediatamente em deletes recentes) ou tipo de delete (menu library
vs dentro do space). Não 100% determinístico em testes curtos.

**Solução:** reconciler trata **ambos** os casos:
- Sumiu de tudo → marca como deletado (já cumprido pelo
  preserved_missing do listing global)
- Sumiu de listing MAS está em algum space → marca `_orphan: true`
  no `threads_index.json` do space (preservation passiva)

### 11. Browser singleton lock travado
**Sintoma:** background bash anterior crashou e deixou
`.storage/perplexity-profile/SingletonLock`. Próximas runs falhavam
com "ProcessSingleton already exists".

**Solução manual:** `rm -f .storage/perplexity-profile/SingletonLock`.

**TODO futuro:** orchestrator poderia limpar lock no startup se
não houver processo Chrome rodando.

### 12. rsync do macOS é versão antiga
**Sintoma:** `rsync --info=progress2` falhou — flag não suportada.

**Solução:** `cp -R` simples. Pra script: documentar como `cp -R` em
todos os helpers.

### 13. Estilo de comunicação cansativo no início
**Feedback do user:** "muito texto", "tá complicado entender", "cara,
onde fica isso?"

**Lição interna:**
- Não jogar plano A-H completo numa resposta inicial
- Não pedir 3 prints quando posso fazer 1
- Não pedir confirmação repetida
- Usar checklists visuais com checkboxes claros
- Quando pedir ação manual, dar instrução visual clara (não jargão de UI)
- Eu mesmo posso navegar via Playwright em vez de pedir prints

**Permanente:** atualizar `memory/feedback_user_style.md` se necessário.

---

## Achados empíricos preserváveis

### Comportamento do servidor Perplexity (2026-05-01)
- **Rename de thread**: `last_query_datetime` bumpa pra hora atual
  (igual ChatGPT update_time). Validado: `a3a6d563` antes 2025-06-27,
  depois rename 2026-05-01T14:58, foi pro topo da lista. **Reconciler
  detecta via incremental normal.**
- **Add to space**: aparece em `list_collection_threads` do space alvo.
  Validado com `83887374` adicionada a Brainstorm Buddy.
- **Delete via menu thread**: `ENTRY_DELETED` no servidor, some de
  tudo. Validado com `83887374`.
- **Delete legacy**: pode virar orphan no `list_collection_threads`.
  Validado com `d344c501`.

### Schema interno Perplexity
- `sources["sources"]` = lista de **strings categóricas** (NÃO dados)
- `blocks[*].web_result_block.web_results` = sources reais (lista de dicts
  com `name`, `snippet`, `url`, `timestamp`)
- `entries[*].mode` em CAPS lock (`COPILOT`, `CONCISE`, `ASI`, `ARTICLE`)
- Pages internamente são threads com `mode='article'` e campo
  `article_info` distintivo
- Artifacts têm `entry_uuid` linkando à thread origem
- Spaces têm `space_type` (private/public), `access`, `user_permission`
- Files de space via `/rest/file-repository/list-files` com body
  `{file_repository_info: {file_repository_type: "COLLECTION", owner_id: <uuid>}}`

### Endpoints REST Perplexity descobertos
| Endpoint | Método | Função |
|---|---|---|
| `/rest/thread/list_ask_threads` | POST | Lista threads do user (paginado offset) |
| `/rest/thread/list_pinned_ask_threads` | POST `{}` | Threads pinadas |
| `/rest/thread/{uuid}` | GET | Fetch thread completo |
| `/rest/collections/list_user_collections` | GET | Lista spaces |
| `/rest/collections/get_collection?collection_slug=X` | GET | Metadata 1 space |
| `/rest/collections/list_collection_threads?collection_slug=X` | GET | Threads em space |
| `/rest/spaces/user-pins` | GET | Spaces pinados |
| `/rest/spaces/{uuid}/pins/threads` | GET | Threads pinned em space |
| `/rest/spaces/{uuid}/tasks` | GET | Tasks Computer em space (Pro) |
| `/rest/file-repository/list-files` | POST | Files em space |
| `/rest/file-repository/download-attachment` | POST `{url, thread_id}` | Refresh URL S3 |
| `/rest/file-repository/download` | POST `{file_url, thread_id}` | Refresh URL S3 (variante) |
| `/rest/article/{slug}` | GET | Fetch page completa |
| `/rest/assets/?limit=N` | GET | Lista artifacts (paginado por next_token) |
| `/rest/assets/pins` | GET | Artifacts pinados |
| `/rest/user/info` | GET | Status user (is_enterprise, is_student) |
| `/rest/user/settings` | GET | Limites + connector_limits |
| `/rest/user/get_user_ai_profile` | GET | AI profile (bio, location, language) |
| `/rest/page/get_related_pages` | GET | Recomendações (não capturado) |

### Endpoints chutados que retornam 404 ou Pro-only
- ~~`/rest/spaces/{uuid}/skills` → 404~~ (path errado — ver errata abaixo)
- `/rest/spaces/{uuid}/links` → 404
- `/rest/collections/{uuid}/threads` → 404 (usa `slug`, não uuid)
- `/rest/page/list*`, `/rest/articles/list*` → 404 (não há listing
  de pages — vêm via SSR no HTML do space)

### Errata 2026-05-01 (probes Chrome MCP)

Descobertas posteriores via probe direto na sessão Chrome (depois da
publicação inicial deste journey):

- **Skills:** endpoint correto é `GET /rest/skills?scope=<X>&scope_id=<UUID>`,
  não `/rest/spaces/{uuid}/skills`. Scopes válidos: `global`, `organization`,
  `collection`, `individual`. Funciona em Pro.
- **Pin de thread:** bug no extractor (`list_all_threads` com `seen: set`
  descartava `is_pinned: true` propagado de `list_pinned_ask_threads`).
  Fix: `seen: dict` + `update()`. `list_pinned_ask_threads` POST `{}`
  sempre funcionou — não era gap de endpoint.
- **Archive de thread:** endpoints write descobertos
  (`POST /rest/thread/archive_thread` body `{context_uuid}` +
  `DELETE /rest/thread/unarchive_thread/<context_uuid>`). Mas testado
  empiricamente: archive em conta Pro é **no-op observável** — backend
  retorna 200 success mas estado não muda em `list_ask_threads`,
  `fetch_thread`, nem em filtros. Feature gated Enterprise via
  `restricted-feature-loader` em Cloudflare Access.
- **Voice:** servidor transcreve áudio e descarta — `query_str` vira
  texto normal. Sem campo distintivo. Limitação upstream.

Detalhes em `perplexity-audit-findings.md`.

---

## Comandos pra rodar

```bash
# Sync completo (capture + reconcile)
PYTHONPATH=. .venv/bin/python scripts/perplexity-sync.py

# Parse merged → parquets
PYTHONPATH=. .venv/bin/python scripts/perplexity-parse.py

# Render Quarto descritivo
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/perplexity.qmd

# Open output
open notebooks/_output/perplexity.html
```

---

## Pra próximas plataformas (Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek)

Lições transferíveis:

1. **Sempre olhar o projeto pai antes** — profiles em `.storage/`,
   dados anteriores em `data/raw/` e `data/merged/`
2. **Network tap > chute** — não chutar URLs de endpoints. Usa
   Playwright `page.on("response")` durante navegação real.
3. **UI name ≠ API name** — Perplexity ensinou: Spaces/collections,
   Pages/articles, Artifacts/assets. Cada plataforma tem suas
   divergências.
4. **SSR pode esconder dados** — Perplexity Pages exigiu DOM-click
   scrape. Outras SPAs podem fazer mesmo.
5. **Conta free limita testes** — features Pro retornam 404 ou modal.
   Documentar como TODO em vez de assumir bug.
6. **Manifest com status pra idempotência** — uploads antigos podem
   ser irrecuperáveis. `failed_upstream_deleted` evita re-tentar.
7. **Reconciler precisa cobrir cenários divergentes de delete**
   (entry-deleted-some-tudo vs orphan-no-space).
8. **Discovery file naming**: raw e merged podem ter nomes diferentes
   (`discovery_ids.json` vs `threads_discovery.json` no Perplexity).
   Reconciler precisa ler ambos.
9. **Server bumps update_time em rename** — caminho incremental
   normal cobre. Não precisa de detecção especial.
10. **Estilo de comunicação direto** — checklists visuais, sem
    jogar opções múltiplas, sem pedir prints quando dá pra navegar.
