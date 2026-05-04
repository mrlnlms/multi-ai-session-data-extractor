# Qwen — technical coverage

## Pipeline

- **Single cumulative folder:** `data/raw/Qwen/` and `data/merged/Qwen/`.
- **Sync orchestrator (2 steps):** `scripts/qwen-sync.py` (capture +
  reconcile).
- **Headless capture.**
- **Auth:** persistent profile in `.storage/qwen-profile-<account>/`
  (generated via `scripts/qwen-login.py`).

## Coverage

Chats + projects + project files captured. Reconciler v3
(FEATURES_VERSION=2): full preservation for convs + projects.

### Reference volume

- 115 chats / 3 projects / 4 project files.
- 1,799 messages / 9 tool_events / 133 branches.

## Canonical parser

`src/parsers/qwen.py` + `_qwen_helpers.py`.

### Coverage

- **8 chat_types mapped to modes:** chat / search / research
  (deep_research) / dalle (t2i+t2v).
- **Branches via flat DAG** (`parentId`/`childrenIds` + `currentId`).
- **`reasoning_content` → `Message.thinking`** (rare — feature of
  QwQ-style models, conditional).
- **`search_results`** (from `info.search_results` blocks) → ToolEvent.
- **t2i/t2v/artifacts** always emit ToolEvent
  (`image/video_generation`, `artifact`).
- **`pinned` → `is_pinned`** (cross-platform).
- **`archived` → `is_archived`** (but always False — see
  [LIMITATIONS.md](../../LIMITATIONS.md#qwen)).
- **`meta.tags` + `feature_config`** preserved in `settings_json`.
- **`content_list[*].timestamp`** → `Message.start_timestamp`/`stop_timestamp`.
- **Project with `custom_instruction`** + `_files` (presigned S3 URLs,
  expire in 6h) → `project_metadata` + `project_docs` parquets.

## Integrated asset download

`scripts/qwen-download-assets.py`. URLs in msgs/projects downloaded via
manifest. Parser resolves `asset_paths` via `assets_manifest.json`.

## Descriptive Quarto

`notebooks/qwen.qmd`: 17MB HTML, render < 30s, primary color purple `#615CED`.

## Validated CRUD scenarios

| Scenario | Result |
|---|---|
| Rename | title matches in parquet, `updated_at` bumps |
| Pin | `is_pinned=True`, `updated_at` bumps |
| Archive | upstream no-op on Pro/free (see [LIMITATIONS.md](../../LIMITATIONS.md#qwen)) |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preserved |

## Related documents

- `docs/platforms/qwen/server-behavior.md` — upstream behavior.

## Commands

```bash
PYTHONPATH=. .venv/bin/python scripts/qwen-sync.py
PYTHONPATH=. .venv/bin/python scripts/qwen-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/qwen.qmd
```
