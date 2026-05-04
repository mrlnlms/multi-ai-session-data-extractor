# Qwen — server behavior (empirically validated)

Mirror of `ChatGPT server behavior` in CLAUDE.md. CRUD diff over
**4 snapshots** (3 from the parent project + 1 current), 2026-04-24 → 2026-05-01.

| Snapshot | Chats |
|---|---|
| Qwen Data/2026-04-24T16-10 | 109 |
| Qwen Data/2026-04-24T17-47 | 109 |
| Qwen Data/2026-04-24T17-48 | 112 |
| current (2026-05-01) | 115 |

## CRUD between consecutive snapshots

| Transition | Added | Removed | Renamed | Pin changed | updated_at bumped |
|---|---|---|---|---|---|
| 16-10 → 17-47 | 0 | 0 | 0 | 0 | 0 |
| 17-47 → 17-48 | 3 | 0 | 0 | 0 | 0 |
| 17-48 → current | 3 | 0 | 0 | 0 | 0 |

## Inferences

- **Add working:** 6 new chats created over 7 days were detected
- **No deletes in this window:** preservation pattern was not exercised.
  When the user deletes, validate with UI battery.
- **No rename/pin/archive in this window:** finer-grained behavior
  (does rename bump updated_at? does archive expose a flag?) can only
  be confirmed via manual UI.
- **`updated_at` did not bump on existing chats:** expected behavior
  because there was also no activity on them. We still don't know if
  rename bumps — TODO battery.

## Schema: confirmed-present features

- ✅ `pinned`: bool in raw schema + parser
- ✅ `archived`: bool in raw schema + parser (0 archived in this base)
- ✅ `project_id`: 3 chats in projects (Teste IA Interaction, Qualia, Travel)
- ✅ `share_id`: field in schema, **0 values in this base** — feature
  exists in UI but not tested
- ✅ `folder_id`: field in schema, **0 values in this base** — folders
  feature exists in UI but not tested
- ✅ 8 `chat_type`: t2t / search / deep_research / t2i / t2v / artifacts /
  learn / null

## UI CRUD battery — 2026-05-01 (Pro account)

User executed 4 actions in the UI; `--full` sync ran after each batch
to force body refetch.

| Action | Chat | Parquet result | updated_at on server |
|---|---|---|---|
| Rename → "Codemarker V2 from mqda" | `8c97d9ab` | ✅ title matches | bumps (2026-02-17 → 2026-05-02) |
| Pin | `240ac30f` | ✅ `is_pinned=True` | bumps (2026-02-20 → 2026-05-02) |
| Archive | `75924b8e` | ⚠️ `is_archived=False` | bumps, but flag does NOT persist |
| Delete | `2d7e6a81` | ✅ `is_preserved_missing=True` | gone from listing |

## Confirmed inferences

- **Rename bumps `updated_at`** (same as ChatGPT, same as Perplexity).
  Normal incremental path covers it — title-diff guardrail stays as
  defense.
- **Pin reflects in `pinned`** in the chat body returned by `/v2/chats/{id}`
  AND in the `/v2/chats/?page=N` listing. Dedicated endpoint
  `/v2/chats/pinned` also returns the chat. Bumps `updated_at`.
- **Delete removes from listing** + reconciler marks `_preserved_missing: True`
  in merged. `last_seen_in_server` preserves the prior date.
- **Archive is an observable upstream no-op** (Qwen Pro/free limitation):
    - Server accepts the request (`updated_at` does bump)
    - Body returns `archived: False` even after the action
    - Endpoint `/v2/chats/archived` exists but returns `len=0`
    - ALL listings (`?archived=true`, `?show_archived=true`,
      `?include_archived=true`, `/all`) still include the chat with the same fields
    - Same pattern as Perplexity Enterprise-only archive
    - **Not an extractor gap** — canonical schema has `is_archived`
      field, just never True on Pro/free account
    - Probe: `scripts/qwen-probe-archived.py`

## Bugs discovered+fixed in this battery

1. **`_get_max_known_discovery(output_dir.parent)` leaked across platforms.**
   Before migrating to a single folder, `output_dir.parent` was the
   platform folder (with timestamped subfolders). After migration, it
   became `data/raw/` → rglob walked all platforms and picked the max
   from ChatGPT (1171) or Claude.ai (835). Fix: pass `output_dir`.
   Applied to all 4 orchestrators (qwen, deepseek, claude_ai, chatgpt).

2. **`discover()` persisted before fail-fast.** If fail-fast aborted,
   discovery_ids.json already had new timestamps and the next run
   loaded prev_map already with new ts → 0 refetched even when there
   were changes. Fix: separate `discover()` (pure fetch) from
   `persist_discovery()` (called by the orchestrator after fail-fast).
   Applied to qwen.

3. **`qwen-sync.py --full` did not propagate to reconcile.** `--full`
   only forced extractor refetch. Reconciler used `to_copy` (read prior
   merged) for chats without updated_at diff, keeping stale bodies.
   Fix: pass `full=args.full` to `run_reconciliation`. Applied to
   qwen-sync.py + deepseek-sync.py + claude-sync.py.

## Other observed features (not tested via parser in this battery)

- ✅ **Clone:** option in the menu (per-chat). Semantics: creates a new
  `chat_id` with copied history — equivalent to "add" in the diff. Skipped
  because it does not test preservation/new state-machine.
- ✅ **Download:** per-chat menu exports JSON (`.json`) or plain text
  (`.txt`). Confirms the parsed schema is essentially the official one
  exposed to the user. No implication for the extractor.
- ✅ **Move to Project:** menu option — testable via `project_id` diff
  probe in consecutive snapshots.
- ✅ **Share:** menu option, populates `share_id`. Not exercised.
- ✅ **Folder:** `folder_id` in schema, not exercised.
