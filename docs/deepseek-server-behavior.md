# DeepSeek — comportamento do servidor (validado empiricamente)

CRUD diff inicial sobre **2 snapshots** (1 do projeto-pai + 1 atual),
2026-04-24 → 2026-05-01. Posteriormente complementado por **bateria CRUD UI
ao vivo** (ver seção dedicada abaixo).

| Snapshot | Sessions |
|---|---|
| DeepSeek Data/2026-04-24T16-03 | 78 |
| current (2026-05-01) | 79 |

## CRUD entre snapshots históricos

| Transicao | Added | Removed | Renamed | Pin changed | updated_at bumped |
|---|---|---|---|---|---|
| 16-03 → current | 1 | 0 | 0 | 0 | 0 |

Snapshots históricos só cobrem `add` (1 sessão nova criada). Rename / pin /
delete validados depois via bateria CRUD UI ao vivo (seção abaixo).

## Schema: enums confirmados presentes

### `status` (per msg)
- `FINISHED` — completou normalmente (716/722 msgs)
- `INCOMPLETE` — interrompida ou falhou (5 msgs)
- `WIP` — gerando (1 msg)

### `search_status` (per msg quando search habilitado)
- `FINISHED` (so valor visto)

### `agent` (session level)
- `chat` (so valor visto nesta base — backend tem `agent` mode mas usuario nao
  tem sessions desse tipo)

### `model_type` (session level)
- `default` (78 sessions)
- `expert` (1 session) — **R1 reasoner mode**, mapeado pra `mode='research'`
  no parser canonico
- `thinking` / `reasoner` — mapeados tb pra research (precaucao, nao vistos
  empiricamente)

## Features capturadas no parser

- ✅ `pinned` per-session → `is_pinned`
- ✅ `current_message_id` (int) + `parent_id` → branches DAG plano
- ✅ `thinking_content` + `thinking_elapsed_secs` → `Message.thinking` +
  attachments_json
- ✅ `accumulated_token_usage` → `Message.token_count`
- ✅ `search_results` (lista de dicts com title/url/metadata) → ToolEvent +
  `Message.citations_json`
- ✅ `feedback` (thumbs up/down) → `attachments_json.feedback`
- ✅ `tips` (sugestoes da plataforma) → `attachments_json.tips`
- ✅ `ban_edit` / `ban_regenerate` (UI flags) → `attachments_json`
- ✅ `incomplete_message` → `Message.finish_reason='incomplete'` +
  `attachments_json.incomplete_message`
- ✅ `files` per msg → `Message.attachment_names`

## Bateria CRUD UI — 2026-05-01

User executou 3 acoes na UI; sync incremental rodou (bug 2 fix preventivo
ja aplicado).

| Acao | Chat | Resultado parquet | updated_at no servidor |
|---|---|---|---|
| Rename → "Meta Analytics Explicado" | `1d4823f1` | ✅ title bate | bumpa pra 2026-05-02 |
| Pin → "Data Governance vs Research Ops" | `37ca105e` | ✅ `is_pinned=True` | bumpa pra 2026-05-02 |
| Delete → "Olá, eu tenho uma planilha no go" | `a7087bd3` | ✅ `is_preserved_missing=True` | sumiu do listing |

## Inferencias confirmadas

- **Rename bumpa `updated_at`** (igual ChatGPT, Perplexity, Qwen). Caminho
  incremental cobre — fetcher refetcha e parser pega title novo do body.
- **Pin reflete em `pinned`** no listing imediatamente. Bumpa `updated_at`.
- **Delete remove do listing** + reconciler marca `_preserved_missing: True`
  + `last_seen_in_server` preserva data anterior.
- Sync detectou capture: `discovered=78, fetched=2, reused=76` —
  filtro incremental funcionando corretamente apos bug 2 fix
  (separacao discover/persist_discovery).

## Bugs descobertos+fixados durante bateria CRUD do Qwen (preventivos aqui)

A bateria CRUD do Qwen (2026-05-01) descobriu 3 bugs estruturais que
afetavam todos os 4 orchestrators (qwen, deepseek, claude_ai, chatgpt).
Fixes aplicados preventivamente em DeepSeek antes da própria bateria —
por isso o sync rodou limpo na primeira tentativa:

1. **`_get_max_known_discovery(output_dir.parent)` vazava entre plataformas.**
   Após migração pra pasta única, `parent` virou `data/raw/` e rglob
   percorria todas as plataformas, pegando máximo de Claude.ai (835) ou
   ChatGPT (1171). Fix: passar `output_dir`. Aplicado em
   `src/extractors/deepseek/orchestrator.py`.

2. **`discover()` persistia `discovery_ids.json` antes do fail-fast.** Se
   abortasse, próxima run carregava `prev_map` já com novos timestamps e
   deixava de refetchar bodies que mudaram. Fix: separar `discover()` (puro
   fetch) de `persist_discovery()` (chamado pelo orchestrator pós fail-fast).
   Aplicado em `src/extractors/deepseek/discovery.py`.

3. **`--full` no sync não propagava pro reconciler.** `--full` só forçava
   extractor refetch; reconciler ainda usava cache stale do merged. Fix:
   passar `full=args.full` ao `run_reconciliation`. Aplicado em
   `scripts/deepseek-sync.py`.

## Outras pendencias (nao bloqueantes — feature edges)

- [ ] **Sessao agent mode:** abrir agent, capturar, conferir schema diff
- [ ] **Reasoner R1 (expert):** sessao com reasoning_content cheio +
  thinking_elapsed (1 ja foi capturada)
- [ ] **Files de msg em conta com upload:** schema completo do `files[]`
