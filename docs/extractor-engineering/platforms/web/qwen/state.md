# Qwen — technical coverage

## Pipeline

- **Single cumulative folder:** `data/raw/Qwen/` and `data/merged/Qwen/`.
- **Sync orchestrator (2 steps):** `scripts/qwen-sync.py` (capture +
  reconcile).
- **Headless capture.**
- **Auth:** default persistent profile in `.storage/qwen-profile-default/`
  (generated via `scripts/qwen-login.py`). The token may expire even when the
  profile still opens; validate a minimal API list request before a sync.

## Coverage

Chats + projects + project files captured. Reconciler v3
(FEATURES_VERSION=2): full preservation for convs + projects.

### Latest validated collection — 2026-08-30

- The previous token was expired; after interactive login, a one-page API read
  confirmed the renewed authorization before capture.
- Incremental discovery found 144 current chats, 6 projects, and 15 project
  files. No conversation bodies required refetch and there were no fetch
  errors.
- Reconciliation retained 144 current chats plus 1 preserved-missing record
  (145 total); all 6 current projects were retained.
- Assets: 15 downloaded, 355 existing assets skipped, and 5 URLs unavailable
  upstream. Conversation preservation and parsing were unaffected.
- The parser produced 145 conversations, 2,157 messages, 9 tool events,
  175 branches, 6 projects, and 15 project docs; the unified parquets were
  regenerated.

### Historical reference volume

- 115 chats / 3 projects / 4 project files at the original validation point.
- 1,799 messages / 9 tool events / 133 branches.

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
  [known-limitations.md](../../../known-limitations.md#qwen)).
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
| Archive | upstream no-op on Pro/free (see [known limitations](../../../known-limitations.md#qwen)) |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preserved |

## Related documents

- `docs/extractor-engineering/platforms/web/qwen/server-behavior.md` — upstream behavior.

## Commands

```bash
PYTHONPATH=. .venv/bin/python scripts/qwen-sync.py
PYTHONPATH=. .venv/bin/python scripts/qwen-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/qwen.qmd
```
