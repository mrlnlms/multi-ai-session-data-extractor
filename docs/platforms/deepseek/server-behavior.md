# DeepSeek — server behavior (empirically validated)

Initial CRUD diff over **2 snapshots** (1 from the parent project + 1
current), 2026-04-24 → 2026-05-01. Later supplemented by a **live UI CRUD
battery** (see dedicated section below).

| Snapshot | Sessions |
|---|---|
| DeepSeek Data/2026-04-24T16-03 | 78 |
| current (2026-05-01) | 79 |

## CRUD between historical snapshots

| Transition | Added | Removed | Renamed | Pin changed | updated_at bumped |
|---|---|---|---|---|---|
| 16-03 → current | 1 | 0 | 0 | 0 | 0 |

Historical snapshots only cover `add` (1 new session created). Rename / pin /
delete validated later via the live UI CRUD battery (section below).

## Schema: confirmed enums present

### `status` (per msg)
- `FINISHED` — completed normally (716/722 msgs)
- `INCOMPLETE` — interrupted or failed (5 msgs)
- `WIP` — generating (1 msg)

### `search_status` (per msg when search enabled)
- `FINISHED` (only value seen)

### `agent` (session level)
- `chat` (only value seen in this base — backend has `agent` mode but the
  user has no sessions of that type)

### `model_type` (session level)
- `default` (78 sessions)
- `expert` (1 session) — **R1 reasoner mode**, mapped to `mode='research'`
  in the canonical parser
- `thinking` / `reasoner` — also mapped to research (precaution, not seen
  empirically)

## Features captured in the parser

- ✅ `pinned` per-session → `is_pinned`
- ✅ `current_message_id` (int) + `parent_id` → flat DAG branches
- ✅ `thinking_content` + `thinking_elapsed_secs` → `Message.thinking` +
  attachments_json
- ✅ `accumulated_token_usage` → `Message.token_count`
- ✅ `search_results` (list of dicts with title/url/metadata) → ToolEvent +
  `Message.citations_json`
- ✅ `feedback` (thumbs up/down) → `attachments_json.feedback`
- ✅ `tips` (platform suggestions) → `attachments_json.tips`
- ✅ `ban_edit` / `ban_regenerate` (UI flags) → `attachments_json`
- ✅ `incomplete_message` → `Message.finish_reason='incomplete'` +
  `attachments_json.incomplete_message`
- ✅ `files` per msg → `Message.attachment_names`

## UI CRUD battery — 2026-05-01

User executed 3 actions in the UI; incremental sync ran (preventive bug 2
fix already applied).

| Action | Chat | Parquet result | server updated_at |
|---|---|---|---|
| Rename → "Meta Analytics Explicado" | `1d4823f1` | ✅ title matches | bumps to 2026-05-02 |
| Pin → "Data Governance vs Research Ops" | `37ca105e` | ✅ `is_pinned=True` | bumps to 2026-05-02 |
| Delete → "Olá, eu tenho uma planilha no go" | `a7087bd3` | ✅ `is_preserved_missing=True` | gone from listing |

## Confirmed inferences

- **Rename bumps `updated_at`** (same as ChatGPT, Perplexity, Qwen). The
  incremental path covers it — fetcher refetches and parser picks up the
  new title from the body.
- **Pin reflects in `pinned`** in the listing immediately. Bumps `updated_at`.
- **Delete removes from listing** + reconciler marks `_preserved_missing: True`
  + `last_seen_in_server` preserves the previous date.
- Sync detected the capture: `discovered=78, fetched=2, reused=76` —
  incremental filter working correctly after bug 2 fix
  (discover/persist_discovery separation).

## Bugs found+fixed during the Qwen CRUD battery (preventive here)

The Qwen CRUD battery (2026-05-01) uncovered 3 structural bugs that
affected all 4 orchestrators (qwen, deepseek, claude_ai, chatgpt).
Fixes applied preventively to DeepSeek before its own battery —
which is why sync ran clean on the first attempt:

1. **`_get_max_known_discovery(output_dir.parent)` leaked across platforms.**
   After the migration to the single folder, `parent` became `data/raw/`
   and rglob walked all platforms, picking up the maximum from Claude.ai
   (835) or ChatGPT (1171). Fix: pass `output_dir`. Applied in
   `src/extractors/deepseek/orchestrator.py`.

2. **`discover()` persisted `discovery_ids.json` before fail-fast.** If
   it aborted, the next run loaded `prev_map` already with new timestamps
   and stopped refetching bodies that had changed. Fix: separate
   `discover()` (pure fetch) from `persist_discovery()` (called by the
   orchestrator after fail-fast). Applied in
   `src/extractors/deepseek/discovery.py`.

3. **`--full` in sync did not propagate to the reconciler.** `--full` only
   forced the extractor to refetch; the reconciler still used stale merged
   cache. Fix: pass `full=args.full` to `run_reconciliation`. Applied in
   `scripts/deepseek-sync.py`.

## Other pending items (non-blocking — feature edges)

- [ ] **Agent mode session:** open agent, capture, check schema diff
- [ ] **R1 reasoner (expert):** session with full reasoning_content +
  thinking_elapsed (1 already captured)
- [ ] **Files per msg in account with upload:** full schema of `files[]`
