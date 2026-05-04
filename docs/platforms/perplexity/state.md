# Perplexity — cobertura técnica

## Pipeline

- **Pasta única cumulativa:** `data/raw/Perplexity/` e `data/merged/Perplexity/`.
- **Sync orquestrador (2 etapas):** `scripts/perplexity-sync.py`
  (capture + reconcile). Captura tudo num shot (sem etapa separada de
  assets).
- **Captura:** **headed** (Cloudflare 403 em headless — documentado por
  design em `perplexity/api_client.py:12-13`).
- **Auth:** profile persistente em `.storage/perplexity-profile-<conta>/`
  (gerado via `scripts/perplexity-login.py`).

## Cobertura

Threads + spaces + pages (dentro de Bookmarks) + threads em spaces +
files de space + assets/artifacts metadata + assets binários + thread
attachments (com manifest `failed_upstream_deleted` para S3 cleanup
upstream) + user metadata (info, settings, ai_profile).

Reconciler: preservation completa (orphans + ENTRY_DELETED), idempotente.
Saída em `data/merged/Perplexity/perplexity_merged_summary.json` +
`LAST_RECONCILE.md` + `reconcile_log.jsonl`.

### Volume de referência

- 82 conversations (~41 copilot + ~37 concise + 4 research/pages).
- 374 messages.
- 2312 tool_events (2134 search_result + 168 media_reference + 9 asset_generation).
- 81 branches.

## Parser canônico

`src/parsers/perplexity.py`:

- Pages tem `conversation_id='page:<slug>'`.
- Search results extraídos de `blocks[*].web_result_block.web_results`.
- Idempotente (~1s pra rodar).

## Quarto descritivo

`notebooks/perplexity.qmd`: 22MB HTML self-contained.

## Bateria UI + probe Chrome MCP — gaps fechados

- **Pin de thread em library:** bug em `list_all_threads` (`seen` como
  `set` em vez de `dict`) descartava `is_pinned: true` quando thread já
  aparecia em `list_ask_threads`. Fix: merge dict-based propaga flag.
- **Skills em spaces:** endpoint
  `/rest/skills?scope=collection&scope_id=<UUID>` descoberto via probe
  (scope enum: `global`/`organization`/`collection`/`individual`).
  Implementado `list_collection_skills` + `list_user_skills`.
- **Archive de thread: Enterprise-only** (ver
  [LIMITATIONS.md](../../LIMITATIONS.md#perplexity)).
- **Voice em Perplexity:** comportamento upstream (servidor transcreve
  e descarta áudio).

## Comportamento do servidor

- Rename bumpa `last_query_datetime` (igual ChatGPT).
- Delete via menu = ENTRY_DELETED some de tudo.
- Threads antigas em space podem virar orphan se deletadas.

## Documentos relacionados

- Probes: 7 scripts em `scripts/perplexity-probe-*.py`.

## Comandos

```bash
PYTHONPATH=. .venv/bin/python scripts/perplexity-sync.py
PYTHONPATH=. .venv/bin/python scripts/perplexity-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/perplexity.qmd
```
