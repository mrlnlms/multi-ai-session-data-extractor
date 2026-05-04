# Qwen — cobertura técnica

## Pipeline

- **Pasta única cumulativa:** `data/raw/Qwen/` e `data/merged/Qwen/`.
- **Sync orquestrador (2 etapas):** `scripts/qwen-sync.py` (capture +
  reconcile).
- **Captura headless.**
- **Auth:** profile persistente em `.storage/qwen-profile-<conta>/`
  (gerado via `scripts/qwen-login.py`).

## Cobertura

Chats + projects + project files capturados. Reconciler v3
(FEATURES_VERSION=2): preservation completa convs + projects.

### Volume de referência

- 115 chats / 3 projects / 4 project files.
- 1.799 messages / 9 tool_events / 133 branches.

## Parser canônico

`src/parsers/qwen.py` + `_qwen_helpers.py`.

### Cobertura

- **8 chat_types mapeados pra modes:** chat / search / research
  (deep_research) / dalle (t2i+t2v).
- **Branches via DAG plano** (`parentId`/`childrenIds` + `currentId`).
- **`reasoning_content` → `Message.thinking`** (raro — feature de
  modelos QwQ-style, condicional).
- **`search_results`** (de blocks `info.search_results`) → ToolEvent.
- **t2i/t2v/artifacts** sempre emitem ToolEvent
  (`image/video_generation`, `artifact`).
- **`pinned` → `is_pinned`** (cross-platform).
- **`archived` → `is_archived`** (mas sempre False — ver
  [LIMITATIONS.md](../../LIMITATIONS.md#qwen)).
- **`meta.tags` + `feature_config`** preservados em `settings_json`.
- **`content_list[*].timestamp`** → `Message.start_timestamp`/`stop_timestamp`.
- **Project com `custom_instruction`** + `_files` (presigned S3 URLs,
  expiram 6h) → `project_metadata` + `project_docs` parquets.

## Asset download integrado

`scripts/qwen-download-assets.py`. URLs em msgs/projects baixadas via
manifest. Parser resolve `asset_paths` via `assets_manifest.json`.

## Quarto descritivo

`notebooks/qwen.qmd`: 17MB HTML, render < 30s, cor primária roxo `#615CED`.

## Cenários CRUD validados

| Cenário | Resultado |
|---|---|
| Rename | title bate em parquet, `updated_at` bumpa |
| Pin | `is_pinned=True`, `updated_at` bumpa |
| Archive | no-op upstream em Pro/free (ver [LIMITATIONS.md](../../LIMITATIONS.md#qwen)) |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preservado |

## Documentos relacionados

- `docs/platforms/qwen/server-behavior.md` — comportamento upstream.

## Comandos

```bash
PYTHONPATH=. .venv/bin/python scripts/qwen-sync.py
PYTHONPATH=. .venv/bin/python scripts/qwen-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/qwen.qmd
```
