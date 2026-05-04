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

Caminho default: `streamlit run dashboard/app.py`. Se nao reflete
automaticamente, eh bug do dashboard — corrige antes de declarar plataforma
"shipped".

**Sintoma de que esqueci disso:** declarei plataforma pronta sem ter aberto
o dashboard. Furo: `notebooks/<source>.qmd` rendiriza, parquets estao em
`data/processed/<Source>/`, mas a tabela do dashboard ainda mostra ❌.
Resolver antes de fechar.

## Status (2026-05-03)

Ciclo end-to-end por plataforma documentado em
`docs/platforms/<plat>/state.md` — **conferir la antes de propor refatoracao
ou script novo**. Resumo:

| Plataforma | Capture | Reconcile | Sync | Parser v3 | Quarto | state.md | Notas |
|---|---|---|---|---|---|---|---|
| ChatGPT | ✅ | ✅ | ✅ (4 etapas) | ✅ | ✅ | [chatgpt/state.md](docs/platforms/chatgpt/state.md) | 1171 convs, 6 CRUD validados |
| Claude.ai | ✅ | ✅ | ✅ (3 etapas) | ✅ | ✅ | [claude-ai/state.md](docs/platforms/claude-ai/state.md) | 24k msgs / 16k events, MCP, project_docs |
| Qwen | ✅ | ✅ | ✅ (2 etapas) | ✅ | ✅ | [qwen/state.md](docs/platforms/qwen/state.md) | shipped 2026-05-01 (3/4 CRUD) |
| DeepSeek | ✅ | ✅ | ✅ (2 etapas) | ✅ | ✅ | [deepseek/state.md](docs/platforms/deepseek/state.md) | shipped 2026-05-01 (3/3 CRUD), R1 thinking 31% |
| Gemini | ✅ | ✅ | ✅ (3 etapas multi-conta) | ✅ | ✅ | [gemini/state.md](docs/platforms/gemini/state.md) | shipped 2026-05-02, 2 contas, 4/4 CRUD |
| NotebookLM | ✅ | ✅ | ✅ (3 etapas multi-conta) | ✅ | ✅ | [notebooklm/state.md](docs/platforms/notebooklm/state.md) | shipped 2026-05-02, 9 parquets, account-3 legacy |
| Perplexity | ✅ | ✅ | ✅ (2 etapas) | ✅ | ✅ | [perplexity/state.md](docs/platforms/perplexity/state.md) | 82 convs, 4 spaces, 1 orphan |

**CLI (3 fontes adicionais — dado local em vez de captura web):**

| CLI | Source | Copy script | Parser v3 | Status |
|---|---|---|---|---|
| Claude Code | claude_code | `cli-copy.py --source claude_code` | ✅ shipped 2026-05-03 | 3742 convs / 136k msgs / 78k tool_events |
| Codex | codex | `cli-copy.py --source codex` | ✅ shipped 2026-05-03 | 112 convs / 2.6k msgs / 6.1k tool_events |
| Gemini CLI | gemini_cli | `cli-copy.py --source gemini_cli` | ✅ shipped 2026-05-03 | 12 convs / 181 msgs / 84 tool_events |

**Manual saves** (parser via `scripts/manual-saves-sync.py` — re-mapeiam
source pra plataforma original):

| Parser | source destino | capture_method | Convs |
|---|---|---|---|
| `clippings_obsidian` | chatgpt (20), claude_ai (1) | `manual_clipping_obsidian` | 21 |
| `copypaste_web` | chatgpt (1), claude_ai (1), gemini (2), qwen (1) | `manual_copypaste` | 5 |
| `terminal_claude_code` | claude_code (3) | `manual_terminal_cc` | 3 |

Total: 29 convs / 403 msgs / 70 tool_events. Output em
`<source>_manual_<table>.parquet` em cada `data/processed/<Plataforma>/`.
Quartos fazem UNION via `setup_views_with_manual()` em
`src/parsers/quarto_helpers.py`.

**Schema v3.2 (2026-05-03):** `Conversation.capture_method` (default
`'extractor'`, manuais sobrescrevem). Permite distinguir extractor vs
manual-saves vs futuras fontes externas no mesmo parquet via UNION.

**External preservado (`data/external/`, ~2.0GB total — sem parser canonico):**

| Categoria | Tamanho | Conteudo |
|---|---|---|
| `manual-saves/` | 1.8MB | Inputs ativos pros 3 parsers manuais (parsavel) |
| `openai-gdpr-export/` + archive | 1.0GB | Exports GDPR oficiais OpenAI |
| `chatgpt-extension-snapshot/2026-03-27/` | 51MB | conversations.json + memories.md + instructions.json |
| `claude-ai-snapshots/` | 360MB | snapshots brutos pre-extractor |
| `deepseek-snapshots/2026-03-27/` | 3.2MB | UI export pre-extractor |
| `deep-research-md/` | 208KB | 2 .md exportados manualmente (nao parsado) |
| `notebooklm-snapshots/more-design-2026-03-30/` | 594MB | Captura legacy da conta extinta (parsed → account-3) |
| `perplexity-orphan-threads/` | 56KB | 1 thread Perplexity deletada do servidor |

Padrao: snapshots via UI das plataformas vão pra `<plat>-snapshots/<date>/`,
mantendo arquivos originais.
README em `data/external/README.md`.

## Limpeza de raws 2026-05-03

Pai foi de 25G → 4.4G; filho 11G; 0 missing em todas as 10 sources.
Detalhes + cross-val table em `docs/local/housekeeping/cleanup-2026-05-03.md`
(gitignored).

## TODOs com probe pendente

**Zero TODOs reais pendentes** (validado 2026-05-04). Os 4 originais foram
todos resolvidos ou re-enquadrados apos validacao empirica:

- ChatGPT Pass 2 voice DOM: 127/131 voice msgs ja tem texto via Pass 1 — nao vale ativar.
- NotebookLM `extract_chat_turns`: 0/143 notebooks tem chat populado — nao eh bug, eh estado dos dados.
- Gemini Search/grounding citations: **fechado 2026-05-04** (commit 6a84c8a) — 416 search results em 9 messages.
- NotebookLM mind map tree: **fechado 2026-05-04** (commit 00f47af) — 75/141 mind maps com tree completa.

## Backlog principal

1. ~~`notebooks/00-overview.qmd`~~ **SHIPPED 2026-05-04** — visao consolidada
   cross-plataforma via DuckDB UNION ALL. 4 qmds: geral, web, cli, rag.
   Template em `_template_overview.qmd`. Materializa `data/unified/` via
   `scripts/unify-parquets.py` (11 parquets — 4 canonicos + 7 auxiliares).
2. **DVC pipeline pra consumers externos** — versionar canonicos via DVC,
   pipelines de analise consumem via `dvc import-url`.
3. **Pos-shipping:** publicacao opensource (sanitizar credenciais, README,
   exemplos).

## Cross-feature checks (pin, archive, voice, share)

Quando descobrir feature nova numa plataforma, **checar empiricamente nas
outras**. Tabela cumulativa em `docs/cross-platform-features.md`.

## Comportamento do servidor por plataforma

- ChatGPT: `docs/platforms/chatgpt/server-behavior.md`
- Qwen: `docs/platforms/qwen/server-behavior.md`
- DeepSeek: `docs/platforms/deepseek/server-behavior.md`
- Gemini: `docs/platforms/gemini/server-behavior.md`
- NotebookLM: `docs/platforms/notebooklm/server-behavior.md`
- Perplexity: `docs/platforms/perplexity/state.md` (seção "Comportamento do servidor")

## Princípios inegociaveis (decisoes ja tomadas — nao questionar sem motivo forte)

1. **Capturar uma vez, nunca rebaixar** — pasta unica cumulativa +
   `skip_existing` nos downloaders. Binarios sao precious.
2. **Preservation acima de tudo** — convs/sources deletadas no servidor
   viram `_preserved_missing` no merged.
3. **Fail-fast contra discovery flakey** — `_get_max_known_discovery` com
   threshold 20%; aborta antes do fetch se discovery atual <80% do maior
   historico. Aplicado em todos extractors.
4. **Schema canonico eh fronteira** — `src/schema/models.py` define
   `Conversation`, `Message`, `ToolEvent`, `ConversationProject`, `Branch`.
   Extractors entregam raw/merged JSON; parsers entregam parquet nesse
   schema; analise consome parquet read-only.

## Estrutura

```
src/
├── extractors/<source>/      # 6 modulos por plataforma (auth, api_client,
│                             # discovery, fetcher, asset_downloader, orchestrator)
├── reconcilers/<source>.py   # build_plan + run_reconciliation, preserva missing
├── parsers/                  # merged -> parquet (canonico)
│   ├── chatgpt.py            # ⭐ canonico — tree-walk, branches, ToolEvents,
│   │                         #    voice, DALL-E, custom_gpt etc
│   └── <outros>.py           # parsers das outras plataformas
└── schema/models.py          # Conversation, Message, ToolEvent, Branch, ConversationProject

scripts/
├── <source>-login.py         # 1x por plataforma, abre navegador pra login
├── <source>-export.py        # captura conversas (incremental por default)
├── <source>-reconcile.py     # standalone (sync ja chama)
├── <source>-download-assets.py
├── <source>-sync.py          # ⭐ orquestrador (numero de etapas varia)
└── <source>-parse.py         # merged -> parquet canonico

notebooks/
├── _quarto.yml               # config compartilhado (toc lateral, embed, theme)
├── _style.css                # CSS compartilhado
├── _template.qmd             # ⭐ partial universal (1.x schema/sample + 2.x cobertura
│                             #    + 3.x volumes/distrib + 4.x preservation)
├── _template_aux.qmd         # ⭐ partial pras tabelas auxiliares
├── _template_overview.qmd    # ⭐ partial cross-plataforma
├── chatgpt.qmd, claude-ai.qmd, codex.qmd, ...  # ~50 linhas cada — config
│                             #    (SOURCE_KEY, SOURCE_TITLE, SOURCE_COLOR,
│                             #    AUX_TABLES, ACCOUNT_FILTER) +
│                             #    {{< include _template.qmd >}}. 14 qmds total.
├── 00-overview.qmd, ...      # 4 qmds cross-plataforma (geral/web/cli/rag)
└── _output/                  # (gitignored) HTML rendirizado, ~40MB cada

tests/  (514 testes — TODOS devem passar antes de qualquer merge)
data/
├── raw/                      # (gitignored) saida dos extractors
├── merged/                   # (gitignored) saida dos reconcilers
├── processed/                # (gitignored) saida dos parsers (per-source)
├── unified/                  # (gitignored) saida do unify-parquets.py (cross-platform)
└── external/                 # (gitignored) blobs preservados (snapshots, GDPR exports, etc)
.venv/                        # local — Python 3.14, criado em 2026-04-27
                              # setup: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Overview cross-platform (2026-05-04)

`data/unified/` materializa 11 parquets consolidados a partir de
`data/processed/<Source>/`. Concat + dedup PK composta. Idempotente.
Rodar via `scripts/unify-parquets.py` apos os parses individuais.

**Quarto overview** le `data/unified/` direto. 4 qmds cross-plataforma:

- `notebooks/00-overview.qmd` — todas as 10 sources (sem filtro)
- `notebooks/00-overview-web.qmd` — 6 web (chatgpt, claude_ai, perplexity,
  qwen, deepseek, gemini)
- `notebooks/00-overview-cli.qmd` — 3 CLIs (claude_code, codex, gemini_cli)
- `notebooks/00-overview-rag.qmd` — NotebookLM

Per-subset qmd tem ~50L (setup + `SOURCES_FILTER = [...]` + include do
template). Helper `setup_unified_views(con, unified_dir, sources_filter)`
em `quarto_helpers.py` carrega views DuckDB com filtro opcional `WHERE
source IN (...)`.

```bash
PYTHONPATH=. .venv/bin/python scripts/unify-parquets.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview.qmd
```

**Decisao arquitetural:** filho materializa `data/unified/` (interface DVC
pro consumer + overview qmds). Decorrente de "filho eh casa canonica"
(memory `project_canonical_data_home.md`).

**Testes:** `tests/test_unify_parquets.py` (18 testes — identify_table,
source_from_path, dedup PK composta, idempotencia, schema divergente
UNION BY NAME, enriquecimento source).

## Template canonico de notebooks (2026-05-03)

14 qmds compartilham `notebooks/_template.qmd` (~900L) + opcionalmente
`notebooks/_template_aux.qmd` (~200L pra plataformas com aux tables).
Cada per-source qmd tem ~50 linhas — so config + include do template.

**Helpers compartilhados:** `src/parsers/quarto_helpers.py` (1 modulo, 11
funcoes — setup de views, schema/query, formatters, plot).

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
tem o campo. Ex: `summary`, `citations_json`, `thinking`, `interaction_type`,
`account`.

**Per-account filter:** `ACCOUNT_FILTER = "1"` no per-source qmd recria
views lendo direto dos parquets com `WHERE account = 'X'`. Usado por
`gemini-acc-{1,2}.qmd`, `notebooklm-acc-{1,2}.qmd`, `notebooklm-legacy.qmd`.

**40 testes unitarios** em `tests/parsers/test_quarto_helpers.py`.

**Adicionar uma secao nova:** mexer no `_template.qmd` (1 lugar) — aparece
nos 14 qmds automaticamente. Adicionar campo conditional: usar `has_col(con,
table, col)` como guarda.

**Render:** `QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render
notebooks/<plat>.qmd`. Sem `QUARTO_PYTHON`, falha por dep do `.venv`.

## Helpers chave (NAO mexer sem entender)

### `src/extractors/chatgpt/orchestrator.py`
- `_find_last_capture(raw_root)`: ordena por `run_started_at` (NAO por mtime).
  Robusto contra cenario "pasta sem sufixo + pasta com sufixo de hora".
- `_get_max_known_discovery(raw_root)`: rglob recursivo pra incluir backups.
- `DISCOVERY_DROP_ABORT_THRESHOLD = 0.20`

### `scripts/chatgpt-sync.py`
- Orquestra capture + assets + project_sources + reconcile em sequencia.
  Como a pasta `data/raw/ChatGPT/` eh cumulativa, downloaders pulam binarios
  ja existentes via `skip_existing`.

### `src/extractors/chatgpt/project_sources.py`
- `_merge_with_preserved(current, index_path)`: merge cumulativo do indice
  `_files.json`, marca removidas com `_preserved_missing`.

## Comandos comuns

Pre-requisito: `.venv` ativado (`source .venv/bin/activate`) ou usar
`.venv/bin/python` direto.

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

Comandos por plataforma estao em `docs/platforms/<plat>/state.md`.

## Convencoes do projeto (heranca do projeto antigo)

- Commits via `~/.claude/scripts/commit.sh "mensagem"` (forca autor Marlon
  Lemes, bloqueia Co-Authored-By).
- Conventional commits em portugues (feat:, fix:, chore:, docs:, refactor:, test:).
- `data/raw/` gitignored — dados pessoais nunca no repo.
- Idioma codigo: ingles. Comentarios e docs: portugues sem acentos
  preferencialmente.

## Headless vs headed por plataforma

Heranca do AI Interaction Analysis. **Login eh sempre headed (1x por conta,
persiste em `.storage/<plat>-profile-<conta>/`).** **Captura difere:**

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
browser na captura — Cloudflare bloqueia headless com 403 / challenge "Just
a moment...". Documentado por design em `perplexity/api_client.py:12-13`.

**Implicacao operacional:** se rodar Claude/Gemini/NotebookLM/Qwen/DeepSeek
e ver browser abrir, **algo esta errado**. Se for ChatGPT ou Perplexity,
**esperado**.

Ver `docs/glossary.md` pra terminologia (discovery vs merged vs baseline,
preserved_missing, fail-fast, hardlink, etc).

## Gotchas conhecidos

- `chatgpt-export.py` roda `headless=False` no orchestrator (DOM scrape de
  projects + voice pass + Cloudflare). `download-assets.py` roda
  `headless=True` (so chama API com cookies, nao precisa de DOM).
- 8 assets ChatGPT confirmados como **irrecuperaveis** (parents deletados
  no servidor) — `failed=8` em download-assets eh esperado, nao bug.
- DOM scrape de projects as vezes pega 40 em vez de 47 — fail-fast cobre.
- Discovery `/projects` 404a as vezes — fail-fast cobre via fallback
  `/gizmos/discovery/mine` -> DOM scrape.
