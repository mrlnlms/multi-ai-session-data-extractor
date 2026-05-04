# ChatGPT — comportamento do servidor (validado empiricamente)

## `update_time` em rename

Servidor BUMPA `update_time` pra hora atual quando renomeias conv pela
sidebar. Validado em 2026-04-28 com 2 chats antigos (out/2025 e mai/2025) —
ambos saltaram pra 2026-04-28 ao renomear. Implicacao: caminho incremental
normal (`update_time > cutoff`) ja pega rename. Guardrail no
`_filter_incremental_targets` (compara title da discovery vs prev_raw) eh
defesa em profundidade caso comportamento mude.

## Rename de project (nome do project_id, nao IDs)

Sempre detectado via `project_names` re-fetched a cada run. Independente
de `update_time`.

## `/projects` 404 intermitente

Caller tem fallback automatico para `/gizmos/discovery/mine` -> DOM scrape.
Fail-fast cobre quando todos os fallbacks falham juntos (raro).

## O que NAO precisa ser feito (proposto e descartado em 27/abr)

- Re-mergear "do zero" varrendo `_backup-gpt/merged-*` — reconciler ja faz
  preservation naturalmente, merged atual ja tem tudo.
- Refatorar `asset_downloader.py` pra "pool cumulativo" — pasta unica
  cumulativa + `skip_existing` resolve sem mexer no script.
- Criar `chatgpt-reconcile-from-zero.py` ou similar — sync ja orquestra.

**Antes de criar QUALQUER script novo:** conferir se sync, scripts standalone
existentes ou os helpers em `src/` ja resolvem. Se nao tiver certeza, ler
codigo + memory antes de propor.
