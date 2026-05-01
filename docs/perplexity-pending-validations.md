# Perplexity — validações pendentes

Status do extractor em 2026-05-01: **funcionalmente equiparado ao ChatGPT**.
Este doc lista cenários ainda **não validados empiricamente** com dados reais.
**Não são bugs** — o framework cobre todos os casos. Só falta exercitar
ações específicas no produto pra confirmar captura → reconcile → parser.

---

## Parte 1 — Próxima sessão (sem Pro, acionável)

Ações que o user com **conta free** pode fazer pra fechar gaps de cobertura.
Cada uma exige ~1-3min no UI do Perplexity. Após cada ação, rodar
`scripts/perplexity-sync.py && scripts/perplexity-parse.py` valida que o
extractor captura corretamente.

### 1.1 Voice message
- [ ] Abrir Perplexity, achar **🎤 microfone** no campo de pergunta
  (canto direito, entre "Model" e o ícone de áudio)
- [ ] Clicar e fazer 1 pergunta por voz qualquer ("explique a teoria das
  janelas quebradas")
- [ ] Mandar

**O que valida:**
- Parser deve marcar `Message.is_voice=True` (hoje sempre False)
- `voice_direction` deve ser preenchido ('in' pra user)
- Schema da entry pode ter campos novos relacionados a transcription/audio

**Como conferir:** após sync, `data/processed/Perplexity/messages.parquet`
deve ter 1 row com `is_voice=True`.

### 1.2 Compartilhar thread (gerar link público)
- [ ] Em qualquer thread existente, abrir menu (⋯)
- [ ] Clicar em "Share" / "Compartilhar" / "Copy link"
- [ ] Copiar o link gerado e me mandar (ou só anotar o slug)

**O que valida:**
- Schema da thread no raw deve ter `read_write_token` mudado/populado
- `thread_url_slug` pode mudar quando shared
- Possível endpoint novo (`/rest/thread/share` ou similar) — descobrir
  via probe se houver

**Como conferir:** comparar `data/raw/Perplexity/threads/{uuid}.json` antes
e depois — diff em `read_write_token` ou `access_level` ou `privacy_state`.

### 1.3 Renomear um Space
- [ ] Abrir um space (ex: criar novo "ZTeste" ou usar Brainstorm Buddy)
- [ ] Renomear o space
- [ ] Anotar nome antigo + novo

**O que valida:**
- `metadata.json` do space deve ter `title` atualizado
- `_index.json` cumulativo deve refletir
- Reconciler deve detectar via diff

**Como conferir:** após sync,
`data/merged/Perplexity/spaces/{uuid}/metadata.json` deve ter title novo.
LAST_RECONCILE.md deve mostrar `spaces` com count atualizado.

### 1.4 Deletar um Space
- [ ] Criar space efêmero "ZTeste-Delete" só pra esse teste
- [ ] Adicionar nada nele (vazio)
- [ ] Deletar via menu do space

**O que valida:**
- Reconciler deve marcar space como `_preserved_missing: true` no
  `_index.json` cumulativo
- Pasta `spaces/{uuid}/` no merged deve permanecer (preservation)

**Como conferir:** `data/merged/Perplexity/spaces/_index.json` deve ter
o space marcado como preserved.

### 1.5 Pinar e despinar uma thread
- [ ] Em qualquer thread, procurar opção de **pin** (pode estar no menu da
  thread ou na sidebar)
- [ ] Se tiver: pin
- [ ] Verificar se aparece em alguma seção destacada
- [ ] Anotar se a UI free permite ou não

**O que valida:**
- `list_pinned_ask_threads` (que hoje retorna `[]`) deve retornar dados
- Schema da thread no `threads-index.json` pode ter `is_pinned: true`

**Como conferir:** verificar `data/raw/Perplexity/threads-index.json` —
filtrar por `is_pinned=True` deve mostrar a thread.

### 1.6 Connector externo (Google Drive, opcional)
- [ ] No popover do `+`, hover em "Connectors and sources"
- [ ] Clicar em "Add files from cloud"
- [ ] Conectar Google Drive (OAuth)
- [ ] Adicionar 1 arquivo qualquer pelo connector

**O que valida:**
- `/rest/files/list` deve retornar arquivos com `connection_types: ["GOOGLE_DRIVE"]`
- Schema completo do file via connector

**Como conferir:** deveria aparecer dado em
`data/raw/Perplexity/spaces/{space-uuid}/files.json` se o file foi
adicionado a um space com connector. Caso contrário, novo endpoint pode
aparecer em probe.

**Reverter depois:** desconectar connector pra limpar OAuth permission.

### 1.7 Brainstorm Buddy — verificar metadata rico
- [ ] Abrir o space Brainstorm Buddy
- [ ] Verificar se tem campos populated:
  - description
  - instructions
  - suggested_queries
  - primers
  - emoji (já vimos: 🧠)
- [ ] Se vazio, pode preencher 1 ou 2 campos pra testar captura

**O que valida:**
- Schema completo do space metadata
- Campos especiais como `primers` e `instructions` que podem ter conteúdo
  configurado pelo user

**Como conferir:**
`data/merged/Perplexity/spaces/dcde2f19-a373-47fd-a0cb-5466d67dd989/metadata.json`
deve ter os campos populated.

### 1.8 Mover thread entre spaces
- [ ] Pegar 1 thread em algum space (ex: Bookmarks)
- [ ] Remover do Bookmarks
- [ ] Adicionar em outro space (ex: Heatmaps)

**O que valida:**
- `_removed_from_space` flag no threads_index.json (já implementado, mas
  não validado com data real)
- Comportamento de servidor: thread aparece imediatamente no novo space?

**Como conferir:** após sync, threads_index dos dois spaces deve refletir
o movimento.

---

## Parte 2 — Requires Pro (TODO público pra contributors)

Estas validações **exigem conta Pro** ($20/mo) e ficam em aberto até alguém
com Pro testar. Documenta-se aqui pra quem baixar o repo poder
contribuir.

### 2.1 Computer mode (`mode=asi`)
- Endpoint `/rest/spaces/{uuid}/tasks` retorna `{tasks: []}` em conta free
- Em Pro: criar tarefa Computer (ex: "organize meus emails") e ver:
  - Threads geradas com `mode='ASI'` (devem mapear pra `'research'` no parser)
  - Tasks armazenadas em `/rest/spaces/{uuid}/tasks`
  - Possíveis novos endpoints `/rest/computer/*`

**Esperado:** parser já mapeia `ASI` → `research`. Reconciler trata.
Schema da thread pode ter campos extras (steps, plans, agent_actions).

### 2.2 Scheduled tasks
- Botão "Scheduled" no canto superior direito da home (Pro feature)
- Em Pro: criar agendamento ("todo dia me lembre X") e validar:
  - Endpoint próprio (provavelmente `/rest/scheduled/*` ou similar — descobrir)
  - Schema da scheduled task

**Esperado:** novo endpoint pode emergir. Adicionar ao extractor + parser.

### 2.3 Skills em Spaces
- `/rest/spaces/{uuid}/skills` retorna 404 em conta free
- Em Pro: configurar 1 skill custom em um space e validar:
  - Endpoint passa a retornar 200
  - Schema da skill (nome, prompt, etc)

**Esperado:** adicionar `list_space_skills` ao api_client + capturar em
`spaces/{uuid}/skills.json`.

### 2.4 Links em Spaces
- "Add website URL" no space sidebar
- Em Pro (provável): endpoint `/rest/spaces/{uuid}/links` ou similar
- Em Pro: adicionar 1 link e descobrir o endpoint via probe

### 2.5 Deep Research moderno
- Mode lockado em conta free (✓ confirmado)
- Em Pro: criar thread em mode "Deep Research" atual e validar:
  - Mode na entry vem como `COPILOT` (legacy) ou tem novo nome (`DEEP_RESEARCH`)?
  - Schema da entry tem campos extras pra Deep Research moderno
    (multi-step, citations expandidas)?

### 2.6 Modelos AI alternativos
- Lockados em conta free (Sonar/GPT-5.4/GPT-5.5/Gemini 3.1/Claude Sonnet 4.6/Claude Opus 4.7/Kimi K2.6)
- Em Pro: trocar modelo na thread e validar:
  - `display_model` na entry reflete escolha (não só "turbo"/"pplx_alpha")
  - Parser captura corretamente

### 2.7 Model council (Max tier)
- Feature **Pro Max** (acima de Pro): consulta múltiplos modelos
  simultaneamente
- Schema desconhecido. Se algum contributor com Max testar:
  - Captura cada modelo como ToolEvent separado?
  - Aggregação numa só assistant message?

### 2.8 Pages — criar uma própria
- Em conta free: bookmark pages de outros (✓ capturamos 4)
- Em Pro: publicar uma thread COMO Page. Validar:
  - Slug gerado pelo servidor
  - Schema do article gerado
  - Diferenças vs pages bookmarkadas

---

## Parte 3 — Limitações upstream (não-bug, documentado)

Casos onde captura falha por causa do servidor, não do código:

### 3.1 Attachments antigos no S3 expiram
- Perplexity faz cleanup automático de uploads antigos no S3
- Hoje na conta: 6 attachments retornam `404 NoSuchKey`
- Manifest preserva como `failed_upstream_deleted` pra idempotência
  (skip em re-runs)
- **Sem recurso:** Perplexity não disponibiliza arquivo deletado mesmo
  via refresh URL

**Equivalente ao caso ChatGPT:** 8 assets antigos (parents deletados)
são esperados como failed.

### 3.2 Threads orphan em spaces (caso d344c501)
- Comportamento server-side divergente: thread `d344c501-46aa-...` em
  GAS retorna `ENTRY_DELETED` no fetch mas continua referenciada em
  `list_collection_threads` da GAS
- Outras threads deletadas (caso `83887374`): some de tudo
- Hipótese: timing ou contexto da delecão. Não determinístico.
- **Solução adotada:** reconciler cobre ambos os cenários

### 3.3 Slugs de Page não estão no DOM/HTML inicial
- Perplexity SPA Vite não tem `<a href>` literal pra pages
- Slugs gerados via `router.push` no onClick
- **Solução adotada:** DOM-click programático com `expect_navigation` +
  aguarda URL estabilizar (pages têm delay de ~1-2s pra updar URL final
  com hash completo)
- Custo: ~10s por page. Aceitável pra volumes baixos.

### 3.4 Rename de space não bumpa updated_datetime do listing global
- Quando renomeia thread, `last_query_datetime` bumpa (validado).
- Quando renomeia space, comportamento não testado — pode ser que
  `_index.json` reflete via re-fetch direto, ou que
  `updated_datetime` do space também bumpa.
- **TODO:** validar na próxima sessão (item 1.3 da Parte 1).

---

## Como rodar a validação após cada ação

```bash
# 1. Sync (capture + reconcile)
PYTHONPATH=. .venv/bin/python scripts/perplexity-sync.py

# 2. Parse (raw -> parquets canônicos)
PYTHONPATH=. .venv/bin/python scripts/perplexity-parse.py

# 3. Render Quarto (visualizar)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/perplexity.qmd
open notebooks/_output/perplexity.html
```

Após cada ação, comparar:
- `LAST_CAPTURE.md` antes vs depois
- `data/raw/Perplexity/threads-index.json` (diff)
- `data/processed/Perplexity/conversations.parquet` (re-rodar parse)

Se aparecer endpoint novo nos XHRs durante a captura, **provavelmente
tem feature não mapeada** — adicionar ao extractor.

---

## Quando este documento estará "fechado"

- ✅ Parte 1 (sem Pro) toda checada → user fará na próxima sessão
- 🟡 Parte 2 (Pro) marcada como TODO permanente → fica em aberto até
  contributor com Pro testar
- ✅ Parte 3 (upstream) já documentada como esperado/não-bug

Quando Parte 1 for completada, atualizar este doc removendo os checkboxes
e movendo achados pra `docs/perplexity-audit-findings.md`.
