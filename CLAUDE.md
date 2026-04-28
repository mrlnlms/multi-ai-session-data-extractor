# CLAUDE.md — contexto pra agentes que abrirem este projeto

## O que e este projeto

Captura completa e cumulativa de sessoes de AI multi-plataforma (ChatGPT,
Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity). Output em raw
JSON + binarios + parquet canonico. Pensado pra **capturar uma vez, deletar
do servidor, manter local como fonte primaria**.

Ver `README.md` pra setup e uso.

## Status (2026-04-27)

| Plataforma | Capture | Reconcile | Sync orquestrador | Notas |
|---|---|---|---|---|
| ChatGPT | ✅ | ✅ | ✅ (4 etapas, pasta unica) | Preservation completa (conv, source, project deletado), rename detection, fail-fast |
| Claude.ai | ✅ | ✅ | ❌ | Falta sync equivalente |
| Gemini | ✅ | ✅ | ❌ | Idem |
| NotebookLM | ✅ | ✅ | ❌ | 9 tipos de outputs (audio, video, slide deck PDF+PPTX, blog, flashcards, quiz, data table, infographic, mind map) |
| Qwen / DeepSeek / Perplexity | ✅ | ❌ | ❌ | Reconcilers + sync pendentes |

Backlog principal: replicar o padrao do ChatGPT-sync nas outras 6 plataformas.

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

**Estado atual `data/merged/ChatGPT/chatgpt_merged.json`:**
- 1171 convs cumulativas (1168 active + 3 preserved_missing)
- E a fonte de verdade pro ChatGPT
- LAST_RECONCILE.md e reconcile_log.jsonl atualizados a cada run

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
  `ConversationProject`
- Extractors entregam parquet nesse schema
- Analise (em outro projeto, `~/Desktop/AI Interaction Analysis/`) consome
  parquet read-only

## Estrutura

```
src/
├── extractors/<source>/      # 6 modulos por plataforma (auth, api_client,
│                             # discovery, fetcher, asset_downloader, orchestrator)
├── reconcilers/<source>.py   # build_plan + run_reconciliation, preserva missing
├── parsers/                  # raw -> parquet (atualmente bookmarklet legacy
│                             # pro ChatGPT; rewrite consumindo merged em backlog)
└── schema/models.py

scripts/
├── <source>-login.py         # 1x por plataforma, abre navegador pra login
├── <source>-export.py        # captura conversas (incremental por default)
├── <source>-reconcile.py     # standalone (sync ja chama)
├── <source>-download-assets.py
├── <source>-download-project-sources.py  (so ChatGPT por enquanto)
└── chatgpt-sync.py           # ⭐ orquestrador 5 etapas, modelo pras outras

tests/  (170+ testes — TODOS devem passar antes de qualquer merge)
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
