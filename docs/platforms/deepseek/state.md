# DeepSeek — technical coverage

## Pipeline

- **Single cumulative folder:** `data/raw/DeepSeek/` and `data/merged/DeepSeek/`.
- **Sync orchestrator (2 steps):** `scripts/deepseek-sync.py` (capture +
  reconcile).
- **Headless capture.**
- **Auth:** persistent profile in `.storage/deepseek-profile-<account>/`
  (generated via `scripts/deepseek-login.py`).

## Coverage

Chat sessions captured. Reconciler v3 (FEATURES_VERSION=2): no
projects (DeepSeek does not expose them).

### Reference volume

- 79 chat_sessions.
- 722 messages / 20 tool_events / 271 branches.

## Canonical parser

`src/parsers/deepseek.py` + `_deepseek_helpers.py`.

### Coverage

- **R1 reasoning → `Message.thinking`** (~31% of msgs in a reference
  corpus — high coverage).
- **`thinking_elapsed_secs`** summarized in
  `settings_json.thinking_elapsed_total_secs`.
- **`accumulated_token_usage`** → `Message.token_count` (~98% coverage).
- **`pinned` → `is_pinned`** (cross-platform).
- **`agent`** (chat/agent) + **`model_type`** (default/thinking) → `mode`.
  - `model_type='expert'` mapped to `mode='research'` (R1 reasoner).
- **`current_message_id` + `parent_id`** (int IDs) → flat DAG branches.
  ~2.4 branches/conv (DeepSeek has lots of regenerate).
- **`search_results`** (rich structure with title/url/metadata) →
  ToolEvent + `Message.citations_json`.
- **`incomplete_message` + `status`** → `Message.finish_reason` (100% cov.).
- **`status` enum:** `FINISHED`/`INCOMPLETE`/`WIP`.
- **Files per msg** → `attachment_names`.
- **`feedback`/`tips`/`ban_edit`/`ban_regenerate`/`thinking_elapsed_secs`**
  preserved in `Message.attachments_json`.

> **Note:** The legacy parser's old schema was OUTDATED (it expected
> `mapping` + `fragments`, but the current API returns flat `chat_messages`
> with dedicated fields). Parser v3 is a complete rewrite.

## Descriptive Quarto

`notebooks/deepseek.qmd`: 8MB HTML, royal blue color.

## Validated CRUD scenarios

| Scenario | Result |
|---|---|
| Rename | title matches in parquet, `updated_at` bumps |
| Pin | `is_pinned=True`, `updated_at` bumps |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preserved |

## Related documents

- `docs/platforms/deepseek/server-behavior.md` — upstream behavior.

## Commands

```bash
PYTHONPATH=. .venv/bin/python scripts/deepseek-sync.py
PYTHONPATH=. .venv/bin/python scripts/deepseek-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/deepseek.qmd
```
