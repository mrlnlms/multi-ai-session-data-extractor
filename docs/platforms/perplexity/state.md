# Perplexity — technical coverage

## Pipeline

- **Single cumulative folder:** `data/raw/Perplexity/` and `data/merged/Perplexity/`.
- **Sync orchestrator (2 steps):** `scripts/perplexity-sync.py`
  (capture + reconcile). Captures everything in one shot (no separate
  asset step).
- **Capture:** **headed** (Cloudflare 403 in headless — documented by
  design in `perplexity/api_client.py:12-13`).
- **Auth:** persistent profile in `.storage/perplexity-profile-<account>/`
  (generated via `scripts/perplexity-login.py`).

## Coverage

Threads + spaces + pages (inside Bookmarks) + threads in spaces +
space files + assets/artifacts metadata + binary assets + thread
attachments (with `failed_upstream_deleted` manifest for upstream S3
cleanup) + user metadata (info, settings, ai_profile).

Reconciler: full preservation (orphans + ENTRY_DELETED), idempotent.
Output in `data/merged/Perplexity/perplexity_merged_summary.json` +
`LAST_RECONCILE.md` + `reconcile_log.jsonl`.

### Reference volume

- 82 conversations (~41 copilot + ~37 concise + 4 research/pages).
- 374 messages.
- 2312 tool_events (2134 search_result + 168 media_reference + 9 asset_generation).
- 81 branches.

## Canonical parser

`src/parsers/perplexity.py`:

- Pages have `conversation_id='page:<slug>'`.
- Search results extracted from `blocks[*].web_result_block.web_results`.
- Idempotent (~1s to run).

## Descriptive Quarto

`notebooks/perplexity.qmd`: 22MB self-contained HTML.

## UI battery + Chrome MCP probe — gaps closed

- **Thread pin in library:** bug in `list_all_threads` (`seen` as a
  `set` instead of `dict`) discarded `is_pinned: true` when the thread
  already appeared in `list_ask_threads`. Fix: dict-based merge
  propagates the flag.
- **Skills in spaces:** endpoint
  `/rest/skills?scope=collection&scope_id=<UUID>` discovered via probe
  (scope enum: `global`/`organization`/`collection`/`individual`).
  Implemented `list_collection_skills` + `list_user_skills`.
- **Thread archive: Enterprise-only** (see
  [LIMITATIONS.md](../../LIMITATIONS.md#perplexity)).
- **Voice in Perplexity:** upstream behavior (server transcribes and
  discards audio).

## Server behavior

- Rename bumps `last_query_datetime` (same as ChatGPT).
- Delete via menu = ENTRY_DELETED disappears from everywhere.
- Old threads in a space can become orphans if deleted.

## Related documents

- Probes: 7 scripts in `scripts/perplexity-probe-*.py`.

## Commands

```bash
PYTHONPATH=. .venv/bin/python scripts/perplexity-sync.py
PYTHONPATH=. .venv/bin/python scripts/perplexity-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/perplexity.qmd
```
