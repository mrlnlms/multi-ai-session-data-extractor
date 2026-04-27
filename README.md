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

## Status (2026-04-27)

- ChatGPT: ✅ ciclo completo (sync 5 etapas: capture + hardlink + assets +
  sources + reconcile, com fail-fast contra discovery flakey e preservation
  de sources removidas no servidor)
- Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity: extractors
  individuais migrados, falta sync orquestrador equivalente

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
