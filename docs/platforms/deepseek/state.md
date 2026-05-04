# DeepSeek — cobertura técnica

## Pipeline

- **Pasta única cumulativa:** `data/raw/DeepSeek/` e `data/merged/DeepSeek/`.
- **Sync orquestrador (2 etapas):** `scripts/deepseek-sync.py` (capture +
  reconcile).
- **Captura headless.**
- **Auth:** profile persistente em `.storage/deepseek-profile-<conta>/`
  (gerado via `scripts/deepseek-login.py`).

## Cobertura

Chat sessions capturadas. Reconciler v3 (FEATURES_VERSION=2): sem
projects (DeepSeek não expõe).

### Volume de referência

- 79 chat_sessions.
- 722 messages / 20 tool_events / 271 branches.

## Parser canônico

`src/parsers/deepseek.py` + `_deepseek_helpers.py`.

### Cobertura

- **R1 reasoning → `Message.thinking`** (~31% das msgs num corpus de
  referência — alta cobertura).
- **`thinking_elapsed_secs`** sumarizado em
  `settings_json.thinking_elapsed_total_secs`.
- **`accumulated_token_usage`** → `Message.token_count` (~98% cobertura).
- **`pinned` → `is_pinned`** (cross-platform).
- **`agent`** (chat/agent) + **`model_type`** (default/thinking) → `mode`.
  - `model_type='expert'` mapeado pra `mode='research'` (R1 reasoner).
- **`current_message_id` + `parent_id`** (int IDs) → branches DAG plano.
  ~2.4 branches/conv (DeepSeek tem muito regenerate).
- **`search_results`** (estrutura rica com title/url/metadata) →
  ToolEvent + `Message.citations_json`.
- **`incomplete_message` + `status`** → `Message.finish_reason` (100% cob.).
- **`status` enum:** `FINISHED`/`INCOMPLETE`/`WIP`.
- **Files per msg** → `attachment_names`.
- **`feedback`/`tips`/`ban_edit`/`ban_regenerate`/`thinking_elapsed_secs`**
  preservados em `Message.attachments_json`.

> **Nota:** Schema antigo do legacy parser estava DESATUALIZADO (esperava
> `mapping` + `fragments`, mas API atual retorna `chat_messages` flat com
> campos dedicados). Parser v3 é rewrite total.

## Quarto descritivo

`notebooks/deepseek.qmd`: 8MB HTML, cor azul royal.

## Cenários CRUD validados

| Cenário | Resultado |
|---|---|
| Rename | title bate em parquet, `updated_at` bumpa |
| Pin | `is_pinned=True`, `updated_at` bumpa |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preservado |

## Documentos relacionados

- `docs/platforms/deepseek/server-behavior.md` — comportamento upstream.

## Comandos

```bash
PYTHONPATH=. .venv/bin/python scripts/deepseek-sync.py
PYTHONPATH=. .venv/bin/python scripts/deepseek-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/deepseek.qmd
```
