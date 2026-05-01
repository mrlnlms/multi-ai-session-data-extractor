# DeepSeek — comportamento do servidor (validado empiricamente)

CRUD diff sobre **2 snapshots** (1 do projeto-pai + 1 atual),
2026-04-24 → 2026-05-01.

| Snapshot | Sessions |
|---|---|
| DeepSeek Data/2026-04-24T16-03 | 78 |
| current (2026-05-01) | 79 |

## CRUD entre snapshots

| Transicao | Added | Removed | Renamed | Pin changed | updated_at bumped |
|---|---|---|---|---|---|
| 16-03 → current | 1 | 0 | 0 | 0 | 0 |

## Inferencias

- **Add funcionando:** 1 sessao nova criada
- **Sem deletes nesta janela:** preservation pattern nao foi exercitado
- **Sem rename/pin nesta janela:** updated_at logic nao validada empiricamente

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

## Pendencias (requerem UI do usuario)

- [ ] **Rename:** `updated_at` bumpa? (epoch float)
- [ ] **Delete via menu:** chat some? marca preserved_missing?
- [ ] **Pin:** reflete imediatamente em fetch_page?
- [ ] **Sessao agent mode:** abrir agent, capturar, conferir schema diff
- [ ] **Reasoner R1 (expert):** sessao com reasoning_content cheio +
  thinking_elapsed
- [ ] **Files de msg em conta com upload:** schema completo do `files[]`
