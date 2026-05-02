# multi-ai-session-data-extractor

Captura completa e cumulativa de sessoes de AI multi-plataforma. Pensado pra:
**capturar tudo uma vez, deletar do servidor sem medo, manter local como fonte
primaria.**

## Por que existe

Plataformas AI (ChatGPT, Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek,
Perplexity) tem export oficial limitado, frequentemente quebrado, sem garantia
de retencao. Este projeto captura via API interna (ou filesystem, no caso de
manual saves) tudo que existe — conversas, projects, files, artifacts, audios,
videos, slide decks — reconcilia incrementalmente preservando historico de
chats deletados no servidor, e mantem tudo em schema canonico (parquet).

Output desenhado pra ser **fonte autoritativa**: depois de capturado, voce
pode deletar do servidor e continuar usando a plataforma sem perder nada.

## Status (2026-05-02)

**6 de 7 plataformas shipped** — pipeline completo (capture + reconcile +
sync orquestrador + parser v3 + Quarto descritivo) com bateria CRUD UI
validada empiricamente.

| Plataforma | Status | Cobertura distintiva |
|---|---|---|
| **ChatGPT** | shipped (2026-04-28) | 6 cenários CRUD validados, fail-fast, branches via `mapping`, voice, DALL-E, projects, custom GPT |
| **Claude.ai** | shipped (2026-05-01) | thinking, tool_use/result+MCP, branches via parent_uuid, project_docs com content inline |
| **Perplexity** | shipped (2026-05-01) | 81 conversations (threads + pages), spaces, 9 artifacts, search results |
| **Qwen** | shipped (2026-05-01) | 8 chat_types (chat/search/research/dalle), projects com custom_instruction, archive eh upstream no-op em Pro/free |
| **DeepSeek** | shipped (2026-05-01) | R1 reasoning em 31% das msgs, accumulated_token_usage, ~2.4 branches/conv (regenerate intenso) |
| **Gemini** | shipped (2026-05-02) | **Multi-conta** (2 contas Google), schema raw posicional, 8 modelos (Nano Banana, 3 Flash Thinking, etc), 41% das msgs assistant com thinking |
| NotebookLM | backlog | 9 tipos de outputs (audio, video, slide deck, blog, flashcards, quiz, data table, infographic, mind map) |

320 testes passando. Detalhes empíricos em `docs/<plataforma>-server-behavior.md`.

## Glossário

Termos como **discovery**, **merged**, **baseline**, **preserved_missing**,
**fail-fast**, **hardlink** aparecem nos logs e nos LAST_*.md. Pra entender
o que cada um significa e como se relacionam: [docs/glossary.md](docs/glossary.md).

## Headless vs headed por plataforma

Login: sempre headed (1x por conta, persistido em
`.storage/<plataforma>-profile-<conta>/`).

Captura por plataforma:

| Plataforma | Captura |
|---|---|
| Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek | headless ✅ |
| ChatGPT, Perplexity | headed ⚠️ (Cloudflare detecta headless) |

Se rodar uma das 5 primeiras e ver browser abrir, algo está errado.
ChatGPT/Perplexity: esperado.

## Operação no terminal

Comandos comuns (sync, exports individuais, testes, status, rollback):
[docs/operations.md](docs/operations.md).

## Setup

```bash
git clone <repo>
cd multi-ai-session-data-extractor
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## Uso (ChatGPT)

```bash
# 1. Login (1x — abre navegador, logue manualmente, fecha)
python scripts/chatgpt-login.py

# 2. Sync — captura tudo, ja faz reconcile (1 comando)
python scripts/chatgpt-sync.py --no-voice-pass
```

O sync roda 5 etapas em sequencia:

| # | Etapa | O que faz |
|---|---|---|
| 1 | **Captura conversas** | Extractor + fail-fast (aborta se discovery cai >20% vs maior valor historico — protege contra contaminar raw quando `/projects` 404a) |
| 2 | **Hardlink binarios antigos** | Hardlinka assets/ e project_sources/ de runs anteriores (zero bytes extras) — evita rebaixar |
| 3 | **Download assets DELTA** | Canvas + Deep Research extraidos do raw, imagens via API. Skip de existentes (graças ao hardlink) |
| 4 | **Download project_sources DELTA** | Knowledge files dos projects. Sources removidas no servidor sao preservadas com `_preserved_missing: true` |
| 5 | **Reconcile** | Merge cumulativo em `data/merged/ChatGPT/<date>/`. Convs deletadas no servidor sao preservadas |

### Output

```
data/raw/ChatGPT Data <timestamp>/
├── chatgpt_raw.json          # conversas + projects metadata
├── chatgpt_memories.md
├── chatgpt_instructions.json
├── capture_log.json          # run_started_at, totals, errors
├── discovery_ids.json        # IDs descobertos
├── assets/                   # imagens (DALL-E, uploads, Canvas, Deep Research)
└── project_sources/<pid>/    # knowledge files dos projects
    ├── _files.json           # indice (com preserved_missing pra removidas)
    └── <files binarios>

data/merged/ChatGPT/<date>/
├── chatgpt_merged.json       # cumulativo (preserva deletados no servidor)
└── reconcile_log.json
```

### Flags do sync

```bash
python scripts/chatgpt-sync.py --no-voice-pass   # pula DOM voice pass (rapido)
python scripts/chatgpt-sync.py --full            # forca brute force na captura
python scripts/chatgpt-sync.py --no-binaries     # pula etapas 2-4 (so capture + reconcile)
python scripts/chatgpt-sync.py --no-reconcile    # pula etapa 5
python scripts/chatgpt-sync.py --dry-run         # so descoberta
```

### Scripts standalone (debug / re-run isolado)

```bash
python scripts/chatgpt-export.py                                  # so captura
python scripts/chatgpt-download-assets.py "data/raw/<dir>"        # so assets
python scripts/chatgpt-download-project-sources.py "data/raw/<dir>"  # so sources
python scripts/chatgpt-reconcile.py "data/raw/<dir>"              # so reconcile
```

## Dashboard (Fase 1)

Visualizacao descritiva — counts, saude operacional, status por plataforma.
Roda local, single-user, read-only no que o sync produziu.

### Instalacao

`streamlit` e `plotly` ja vem em `requirements.txt`. Se ja rodou
`pip install -r requirements.txt` (ou `pip install -e ".[dev]"`), esta tudo.

### Rodar

```bash
PYTHONPATH=. streamlit run dashboard.py
```

Abre em <http://localhost:8501>. Sidebar tem botao "Recarregar dados" pra
limpar cache depois de um sync rodado fora do dashboard.

Pra detalhes operacionais (background, healthcheck, acesso de outra sessao
Claude via MCP browser ou `streamlit.testing.v1.AppTest`, gotchas), ver
[docs/dashboard-operations.md](docs/dashboard-operations.md). Pra
funcionalidades de cada tela, ver [docs/dashboard.md](docs/dashboard.md).

### O que faz

- **Overview** — totais cross-plataforma, ultima sync global, alerta de
  plataformas atrasadas, timeline de discovery, botao "Atualizar todas".
- **Drill-down por plataforma** — status, ultima captura/reconcile,
  storage local, conteudo capturado (active vs preserved, projects,
  modelos, top projects), historico de capturas e reconciles, botao de
  sync individual, lista de convs preservadas (deletadas no servidor).

### Primeira vez

Sem captura nenhuma, todas as plataformas aparecem como ⚫ "nunca rodou".
Use o botao "Sync esta plataforma" no drill-down — abre browser pro login
inicial. 6 das 7 plataformas tem orquestrador completo
(`<plat>-sync.py`); so NotebookLM ainda usa `notebooklm-export.py`
standalone (sync orquestrador esta no backlog).

### O que **NAO** faz

Catalogo + saude. Nada de analise interpretativa, clustering, sentiment,
deteccao de topicos. Quem quer interpretacao pesada leva os parquets pra
`~/Desktop/AI Interaction Analysis/`.

## Testes

```bash
pytest                                                            # todos
pytest tests/extractors/chatgpt/test_orchestrator_helpers.py -v   # fail-fast + base selection
pytest tests/test_chatgpt_sync.py -v                              # hardlink
pytest tests/extractors/chatgpt/test_project_sources_preserve.py -v  # preservation
```

## Arquitetura

```
data/raw/<source>/<date>/      ← output dos extractors (snapshot por captura)
        ↓
data/merged/<source>/<date>/   ← output dos reconcilers (cumulativo, preserved)
        ↓
data/processed/<source>.parquet  ← parsers (schema canonico, em desenvolvimento)
```

Schema canonico: `Conversation`, `Message`, `ToolEvent`, `ConversationProject`
(em `src/schema/models.py`).

## Convencoes importantes (NAO QUEBRAR)

1. **Capturar uma vez, nunca rebaixar.** Hardlink primeiro, baixar depois so o delta.
2. **Preservation acima de tudo.** Se algo foi capturado uma vez, nao se perde
   (mesmo deletado no servidor). `_preserved_missing` em convs e em sources.
3. **Fail-fast contra discovery flakey.** `/projects` 404a as vezes — sem
   protecao, raw fica corrompido e contamina proxima base incremental.
4. **Schema canonico e fronteira.** Extractors entregam parquet; analise
   consome parquet. Fronteira clara entre captura e analise.
