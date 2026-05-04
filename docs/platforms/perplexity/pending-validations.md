# Perplexity — validações pendentes

Status do extractor em 2026-05-01: **shipped**. Bateria CRUD UI executada
em 2026-05-01 com conta Pro. Detalhes empíricos em
`docs/platforms/perplexity/audit-findings.md` (seção "Bateria UI 2026-05-01") e
`docs/platforms/perplexity/journey-2026-05-01.md`.

Este doc lista o que ficou **fora do escopo** do shipping atual.

---

## Parte 1 — Concluída (2026-05-01)

7 das 8 ações da bateria foram executadas com conta Pro:

- ✅ **Rename de space** (1.3) — validado
- ✅ **Delete de space com preservation** (1.4) — validado
- ✅ **Mover thread entre spaces** (1.8) — validado
- 🟡 **Voice message** (1.1) — texto capturado, áudio não (limitação upstream — servidor descarta áudio)
- 🟡 **Share de thread** (1.2) — só estado final capturado (URL pública gerada não modifica body)
- 🟡 **Brainstorm Buddy metadata rico** (1.7) — 4/5 campos cobertos (skill faltava → fechado depois via probe)
- ❌ **Pin de thread** (1.5) — bug em `list_pinned_ask_threads` (POST exige body `{}`) → **fechado** durante a bateria
- ❌ **Connector externo / GDrive** (1.6) — dropado (redundante)

Gaps secundários identificados e fechados na mesma bateria:
- ✅ Pin de thread em library — bug corrigido em `list_all_threads`
- ✅ Skills em spaces — endpoint `/rest/skills?scope=collection&scope_id=<UUID>` descoberto e implementado
- ✅ Action "Archive" de thread — documentado como Enterprise-only (no-op pra Pro)
- ✅ Voice em Perplexity — comportamento upstream (servidor transcreve e descarta áudio)

---

## Parte 2 — Pro/Max features (TODO público pra contributors)

Estas validações **exigem conta Pro Max** ($40/mo) e ficam em aberto até
alguém testar.

### 2.1 Computer mode (`mode=asi`)
- Endpoint `/rest/spaces/{uuid}/tasks` retorna `{tasks: []}` em conta Pro
- Em Max: criar tarefa Computer (ex: "organize meus emails") e capturar:
  - Threads geradas com `mode='ASI'` (parser já mapeia → `'research'`)
  - Tasks armazenadas em `/rest/spaces/{uuid}/tasks`
  - Possíveis novos endpoints `/rest/computer/*`

### 2.2 Scheduled tasks
- Botão "Scheduled" no canto superior direito da home
- Em Max: criar agendamento ("todo dia me lembre X") e descobrir endpoint

### 2.3 Model council (Max tier)
- Feature Max: consulta múltiplos modelos simultaneamente
- Schema desconhecido. Se contributor com Max testar:
  - Captura cada modelo como ToolEvent separado?
  - Aggregação numa só assistant message?

### 2.4 Modelos AI alternativos no listing
- Lockados em conta Pro: Sonar / GPT-5.4 / GPT-5.5 / Gemini 3.1 / Claude Sonnet 4.6 / Claude Opus 4.7 / Kimi K2.6
- Em Max: trocar modelo na thread e validar `display_model` na entry

### 2.5 Pages — criar uma própria
- Hoje capturamos 4 pages bookmarkadas. Publicar thread COMO Page (Pro feature):
  - Slug gerado pelo servidor
  - Schema do article gerado
  - Diferenças vs pages bookmarkadas

### 2.6 Deep Research moderno
- Mode lockado em Pro. Em Max:
  - Mode na entry vem como `COPILOT` (legacy) ou tem novo nome (`DEEP_RESEARCH`)?
  - Schema da entry tem campos extras (multi-step, citations expandidas)?

---

## Parte 3 — Limitações upstream (documentadas, não-bug)

Casos onde captura falha por causa do servidor, não do código:

### 3.1 Attachments antigos no S3 expiram
- Perplexity faz cleanup automático de uploads antigos no S3
- Hoje na conta: 6 attachments retornam `404 NoSuchKey`
- Manifest preserva como `failed_upstream_deleted` pra idempotência (skip em re-runs)
- **Equivalente ao caso ChatGPT:** 8 assets antigos com parents deletados são esperados como failed

### 3.2 Threads orphan em spaces (caso `d344c501`)
- Thread em GAS retorna `ENTRY_DELETED` no fetch mas continua referenciada em `list_collection_threads`
- Não determinístico (timing ou contexto da deleção)
- **Solução adotada:** reconciler cobre ambos os cenários

### 3.3 Slugs de Page não estão no DOM inicial
- Perplexity SPA Vite gera slugs via `router.push` no onClick
- **Solução adotada:** DOM-click programático com `expect_navigation`
- Custo: ~10s por page. Aceitável pra volumes baixos.

### 3.4 Voice messages — servidor descarta áudio
- Mesmo após Perplexity transcrever, o áudio em si não é exposto na API
- **Sem recurso:** captura de transcript funciona, mas binário do áudio é perdido upstream
