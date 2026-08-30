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

## Sidebar contract refreshed (2026-08-30)

The current UI must not be scraped to discover its data model. A controlled
headed network observation established three independent contracts:

- normal, non-project sidebar chats: `GET /backend-api/conversations` with
  `offset`, `limit`, `order=updated`, `is_archived`, `is_starred`, and
  `hide_snorlax=true`;
- Projects: cursor-paginated `GET /backend-api/gizmos/snorlax/sidebar`;
  each item carries a `gizmo` object, so `Show more` is presentation-only;
- a Project's chats: `GET /backend-api/gizmos/{project_id}/conversations`.

On the observed account the Project index returned 49 unique projects. The
old `/projects` endpoint returned HTTP 405 and must not gate discovery.
`/conversation/{id}` (singular) remains the preservation endpoint because it
returns the complete `mapping` tree. The UI's plural `/conversations/{id}` is
a viewport response (`num_turns=10`) and is not a substitute for raw capture.

The APIRequestContext transport could stall on the current Cloudflare session;
the client therefore performs authenticated requests through `page.evaluate`
when a headed page is available. The implementation uses explicit 60-second
timeouts and browser-side metadata normalization for conversation listings.

## `/projects` intermittent 404

Legacy fallback remains `/gizmos/discovery/mine` -> DOM scrape.
When all three fail together (or `/conversations` listing itself returns
partial — see below), the orchestrator now falls back automatically to
`refetch_known_via_page` instead of raising.

## Headless mode is blocked — re-validated empirically (2026-05-11)

The orchestrator runs `headless=False` because **both** the DOM scrape
and the API path break in headless mode:

1. **DOM scrape** (project discovery via nav menu): the "More" trigger
   element doesn't respond to click in headless. `Locator.wait_for`
   times out after 10s. Discovery returns partial because the project
   path silently fails.

2. **API path** (page.evaluate calling `/api/auth/session` for
   accessToken): the endpoint returns Cloudflare challenge HTML
   (`<html>...Just a moment...`) instead of JSON. The first
   `JSON.parse` of the response throws SyntaxError, blocking even the
   `refetch_known_via_page` fallback.

This was tested 2026-05-11 by flipping `headless=True` for one run.
Discovery returned 138 convs (worse than the 157 the headed run got
the same day, both partial due to upstream listing flakiness), and
the refetch_known fallback then failed at the first batch with
`SyntaxError: Unexpected token '<', "<html><..."`.

Note that `asset_downloader.py` runs `headless=True` successfully —
it uses `context.request` (cookies inherited from a prior headed
session) instead of `page.evaluate`. The browser-mediated path is
what triggers the challenge.

## `/conversations` listing returns partial — autorecover (2026-05-11)

Sometimes `/conversations` listing comes back with a fraction of the real
conversation count (e.g. 157 vs 1168 baseline) — pagination glitch upstream
or rate limiting at the listing endpoint. Validated empirically on
2026-05-11: discovery returned 157, baseline was 1168 (87% drop).

**Pre-fix behavior** (commit `7868ddb`, 2026-04-27): orchestrator raised
`RuntimeError("Discovery suspeita...")`. The dashboard's "Update all"
button turned red, the user had to manually run
`scripts/chatgpt-refetch-known.py` from the terminal. The "fail-fast"
narrative was invented in this project — not inherited from the parent
project (`AI Interaction Analysis/`), where no such guard existed.

**Post-fix behavior:** when discovery drops more than
`DISCOVERY_DROP_FALLBACK_THRESHOLD` (20%) below the historical max, the
orchestrator calls `refetch_known_via_page` automatically using the IDs
already in `chatgpt_raw.json`. This path doesn't depend on listing.

Trade-off: that run takes ~20min (1168 batches of 10 ≈ ~7s each) instead
of the ~80s of an incremental sync. New conversations created since the
last successful discovery are not picked up in this run — they show up in
the next run when listing recovers. Acceptable cost: the alternative was
red error + manual intervention.

`capture_log.jsonl` records `mode: "refetch_known_fallback"` for these
runs so the dashboard can distinguish them.

## `/conversations/batch` limit reduced to 10 (2026-05-11)

Endpoint used to accept batches of 50 conversation_ids; now caps at 10.
Validated empirically: requests with 50 IDs return HTTP 422 with body
`{"detail":[{"type":"value_error","loc":["body"],"msg":"Value error,
conversation_ids must contain at most 10 entries"}]}`.

`scripts/chatgpt-refetch-known.py` default updated 50 -> 10. The endpoint
itself still works for state-only refresh — only the per-batch ceiling
changed upstream.

### Incremental batch currently rejects (2026-08-30)

During the validated incremental run, all four POST calls to
`/conversations/batch` returned HTTP 422, including a final one-ID batch.
The fetcher fell back to the singular endpoint and completed all 31 targets.
Root cause: the page-backed transport serialized the JSON body but omitted
`Content-Type: application/json`. This was fixed and then validated with a
one-ID batch returning a complete mapping. Treat the singular fallback as a
preservation safeguard, not as the expected path.

### Asset availability (2026-08-30)

Of 560 asset pointers, 552 local binaries were preserved by `skip_existing`
and eight upstream downloads failed. These failures did not prevent raw,
reconcile or parse; downloads are intentionally non-destructive and a future
incremental run may retry only the still-missing binaries.

### Reconciler timestamp compatibility (2026-08-30)

Historical merged records may carry ISO-8601 `update_time`; current API
records carry epoch floats. The reconciler normalizes both before comparison.
Without this boundary normalization, reconciliation raises a Python type
comparison error after capture. Regression coverage includes mixed formats.

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
