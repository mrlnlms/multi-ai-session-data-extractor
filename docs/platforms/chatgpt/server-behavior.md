# ChatGPT — server behavior (empirically validated)

## `update_time` on rename

The server BUMPS `update_time` to the current time when you rename a conv
from the sidebar. Validated on 2026-04-28 with 2 old chats (Oct/2025 and
May/2025) — both jumped to 2026-04-28 on rename. Implication: the normal
incremental path (`update_time > cutoff`) already catches renames. The
guardrail in `_filter_incremental_targets` (compares discovery title vs
prev_raw) is defense in depth in case the behavior changes.

## Project rename (project_id name, not IDs)

Always detected via `project_names` re-fetched on every run. Independent
of `update_time`.

## `/projects` intermittent 404

Caller has automatic fallback to `/gizmos/discovery/mine` -> DOM scrape.
Fail-fast covers the case when all fallbacks fail together (rare).

## What does NOT need to be done (proposed and discarded on Apr/27)

- Re-merge "from scratch" by sweeping `_backup-gpt/merged-*` — the reconciler
  already does preservation naturally, and the current merged already has
  everything.
- Refactor `asset_downloader.py` to a "cumulative pool" — the single
  cumulative folder + `skip_existing` solves it without touching the script.
- Create `chatgpt-reconcile-from-zero.py` or similar — sync already
  orchestrates this.

**Before creating ANY new script:** check whether sync, existing standalone
scripts, or the helpers in `src/` already solve it. If unsure, read code +
memory before proposing.
