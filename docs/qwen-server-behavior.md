# Qwen — comportamento do servidor (validado empiricamente)

Espelho de `Comportamento do servidor ChatGPT` no CLAUDE.md. CRUD diff
sobre **4 snapshots** (3 do projeto-pai + 1 atual), 2026-04-24 → 2026-05-01.

| Snapshot | Chats |
|---|---|
| Qwen Data/2026-04-24T16-10 | 109 |
| Qwen Data/2026-04-24T17-47 | 109 |
| Qwen Data/2026-04-24T17-48 | 112 |
| current (2026-05-01) | 115 |

## CRUD entre snapshots consecutivos

| Transicao | Added | Removed | Renamed | Pin changed | updated_at bumped |
|---|---|---|---|---|---|
| 16-10 → 17-47 | 0 | 0 | 0 | 0 | 0 |
| 17-47 → 17-48 | 3 | 0 | 0 | 0 | 0 |
| 17-48 → current | 3 | 0 | 0 | 0 | 0 |

## Inferencias

- **Add funcionando:** 6 novos chats criados ao longo de 7 dias detectados
- **Sem deletes nesta janela:** preservation pattern nao foi exercitado.
  Quando user deletar, validar com bateria UI.
- **Sem rename/pin/archive nesta janela:** behavior mais granular (rename
  bumpa updated_at? archive expoe flag?) so dara pra confirmar com UI manual.
- **`updated_at` nao bumpou em chats existentes:** comportamento esperado
  porque tambem nao houve atividade neles. Ainda nao sabemos se rename
  bumpa — TODO bateria.

## Schema: features confirmadas presentes

- ✅ `pinned`: bool no schema raw + parser
- ✅ `archived`: bool no schema raw + parser (nesta base 0 archived)
- ✅ `project_id`: 3 chats em projects (Teste IA Interaction, Qualia, Travel)
- ✅ `share_id`: campo no schema, **0 valores nesta base** — feature
  existe na UI mas nao testada
- ✅ `folder_id`: campo no schema, **0 valores nesta base** — folders
  feature existe na UI mas nao testada
- ✅ 8 `chat_type`: t2t / search / deep_research / t2i / t2v / artifacts /
  learn / null

## Bateria CRUD UI — 2026-05-01 (Pro account)

User executou 4 acoes na UI; sync `--full` rodou apos cada lote pra
forcar refetch dos bodies.

| Acao | Chat | Resultado parquet | updated_at no servidor |
|---|---|---|---|
| Rename → "Codemarker V2 from mqda" | `8c97d9ab` | ✅ title bate | bumpa (2026-02-17 → 2026-05-02) |
| Pin | `240ac30f` | ✅ `is_pinned=True` | bumpa (2026-02-20 → 2026-05-02) |
| Archive | `75924b8e` | ⚠️ `is_archived=False` | bumpa, mas flag NAO persiste |
| Delete | `2d7e6a81` | ✅ `is_preserved_missing=True` | sumiu do listing |

## Inferencias confirmadas

- **Rename bumpa `updated_at`** (igual ChatGPT, igual Perplexity). Caminho
  incremental normal cobre — guardrail title-diff fica como defesa.
- **Pin reflete em `pinned`** no body do chat retornado pelo `/v2/chats/{id}`
  E no listing `/v2/chats/?page=N`. Endpoint dedicado `/v2/chats/pinned`
  tambem retorna o chat. Bumpa `updated_at`.
- **Delete remove do listing** + reconciler marca `_preserved_missing: True`
  no merged. `last_seen_in_server` preserva data anterior.
- **Archive eh no-op observavel upstream** (limitacao Qwen Pro/free):
    - Servidor aceita request (`updated_at` bumpa de fato)
    - Body retorna `archived: False` mesmo apos action
    - Endpoint `/v2/chats/archived` existe mas retorna `len=0`
    - TODOS os listings (`?archived=true`, `?show_archived=true`,
      `?include_archived=true`, `/all`) ainda incluem o chat com mesmos campos
    - Mesmo padrao do Perplexity Enterprise-only archive
    - **Nao eh gap do extractor** — schema canonico tem `is_archived` field,
      so nunca True em conta Pro/free
    - Probe: `scripts/qwen-probe-archived.py`

## Bugs descobertos+fixados nesta bateria

1. **`_get_max_known_discovery(output_dir.parent)` vazava entre plataformas.**
   Antes da migracao pra pasta unica, `output_dir.parent` era a pasta da
   plataforma (com subpastas timestampeadas). Apos migracao, virou
   `data/raw/` → rglob caminhava todas as plataformas e pegava maximo de
   ChatGPT (1171) ou Claude.ai (835). Fix: passar `output_dir`.
   Aplicado em todos os 4 orchestrators (qwen, deepseek, claude_ai, chatgpt).

2. **`discover()` persistia antes do fail-fast.** Se fail-fast abortava,
   discovery_ids.json ja estava com novos timestamps e proxima run carregava
   prev_map ja com novos ts → 0 refetched mesmo havendo mudancas. Fix:
   separar `discover()` (puro fetch) de `persist_discovery()` (chamado pelo
   orchestrator pos fail-fast). Aplicado em qwen.

3. **`qwen-sync.py --full` nao propagava pro reconcile.** `--full` so
   forcava extractor refetch. Reconciler usava `to_copy` (read merged anterior)
   pra chats sem updated_at diff, mantendo bodies stale. Fix: passar
   `full=args.full` ao `run_reconciliation`. Aplicado em qwen-sync.py +
   deepseek-sync.py + claude-sync.py.

## Outras features observadas (nao testadas via parser nesta bateria)

- ✅ **Clone:** opcao no menu (per-chat). Semantica: cria novo `chat_id`
  com historico copiado — equivalente a "add" no diff. Skip pq nao testa
  preservation/state-machine novo.
- ✅ **Download:** menu per-chat exporta JSON (`.json`) ou plain text
  (`.txt`). Confirma que o schema parseado eh essencialmente o oficial
  exposto ao usuario. Sem implicacao pro extractor.
- ✅ **Move to Project:** opcao no menu — testavel via probe `project_id`
  diff em snapshots consecutivos.
- ✅ **Share:** opcao no menu, popula `share_id`. Nao exercitado.
- ✅ **Folder:** `folder_id` no schema, nao exercitado.
