# Glossary — project terms

To understand logs, status messages, and script output.

---

## The 3 numbers that look alike but are NOT the same

### 1. Discovery (snapshot of the server right now)

**What it is:** how many conversations ChatGPT.com is showing **at this moment**.

**Can it go up?** Yes, when you create a new conv.
**Can it go down?** Yes, when you delete a conv or it expires on the server.
**Is it our data?** No — it's a snapshot of the server's state, reflected by the API.

Where it appears: log `Discovery: {'total': 1168}` during capture.

---

### 2. Merged (our cumulative history)

**What it is:** the local catalog with EVERY conv we've ever seen.

**Can it go up?** Yes, when we capture something new.
**Can it go down?** **No.** Convs deleted on the server become `preserved_missing` but stay here.
**Is it our data?** Yes — it's the local source of truth.

Where it lives: `data/merged/ChatGPT/chatgpt_merged.json`.

---

### 3. Baseline (the fail-fast internal yardstick)

**What it is:** the **highest discovery value** ever recorded in any capture log on disk.

**What's it for?** Detecting when the OpenAI server is flaky and lying. If current discovery drops more than 20% vs the baseline, the system **aborts before saving corrupted data**.

**Is it our data?** No — it's a measurement instrument. It can be reset without losing data.

Function: `_get_max_known_discovery()` in `src/extractors/chatgpt/orchestrator.py`.

---

## Other terms that show up in the logs

### Preserved missing

A conv (or source) that **was in our previous merged but disappeared from the server**. We don't delete it — we mark it with `preserved_missing: true` (in the conv case) or `_preserved_missing: true` (in the source case).

Principle: **never downgrade history even when the server forgets.**

### Fail-fast

Aborts the capture **before saving** when it detects a server bug symptom (discovery much smaller than the history). Threshold: 20% drop.

Reason: without this, raw becomes corrupted and contaminates the next incremental base.

### Hardlink

The same physical file on disk, with **more than one name** (more than one path). It doesn't duplicate space — just extra labels pointing to the same book.

Used when old and new captures reference the same binaries (assets, project_sources). Deleting one path = removing a label. The file is only gone when the last label is removed.

### Raw

The folder `data/raw/ChatGPT/` — direct capture from the server, no reconciliation. Mutated in-place every run. Has `chatgpt_raw.json` + binaries (assets, project_sources) + logs.

### Reconcile

The process that takes the **current raw** + **previous merged** and produces the **new merged** with all preservation applied (deleted convs become preserved, new ones become added, updated ones become updated, unchanged ones become copied).

### Incremental

Capture mode that does NOT refetch everything. Only downloads convs that changed since the last run (comparing `update_time`). Greatly speeds up runs after the first.

### Brute force (`--full`)

Capture mode that **refetches everything**. Use when you suspect raw is corrupted or want a reset.

### Voice pass

Optional stage that scans convs looking for audio messages (Voice Mode) whose text didn't come through the API. For each candidate, opens the conv in the DOM and scrapes the transcript. Slow — can be skipped with `--no-voice-pass`.

### Multi-account

Platforms where the user has **more than one account** and we want to capture all
of them together. Today **Gemini** and **NotebookLM** are multi-account in the project (2 Google
accounts in `.storage/gemini-profile-{1,2}/` and `.storage/notebooklm-profile-{1,2}/`).

Architectural implications:
- Single folder per account: `data/raw/Gemini/account-{N}/` and `data/merged/Gemini/account-{N}/`
- Sync orchestrator (`gemini-sync.py`) iterates both accounts in sequence by default; accepts `--account N` to run just one
- `Conversation.account` ('1' or '2') in the canonical schema; `conversation_id` gets namespace `account-{N}_{uuid}` to prevent collision between accounts
- Dashboard (`_collect_logs()`) aggregates capture/reconcile logs across `account-*/` subfolders
- Quarto: 3 documents (`gemini.qmd` consolidated with stacked bars per account + `gemini-acc-1.qmd` and `gemini-acc-2.qmd` on the canonical template, filtered)

## NotebookLM-specifics

NotebookLM is the only platform that **isn't pure chat** — each notebook
is a workspace that generates up to **9 distinct output types**:

1. **Audio overview** (.m4a) — type=1
2. **Blog post** (markdown) — type=2
3. **Video overview** (.mp4) — type=3
4. **Flashcards/Quiz** (JSON) — type=4
5. **Data table** (JSON) — type=7
6. **Slide deck** (PDF + PPTX) — type=8
7. **Infographic** (JSON) — type=9
8. **Mind map** (tree JSON) — type=10 (custom)

**NotebookLM-specific auxiliary tables** in the parquet:
- `notebooklm_sources.parquet` — uploaded PDFs/links with extracted text
- `notebooklm_source_guides.parquet` — summary + tags + questions per source (RPC tr032e)
- `notebooklm_notes.parquet` — AI-generated notes/briefs
- `notebooklm_outputs.parquet` — the 9 types above
- `notebooklm_guide_questions.parquet` — questions suggested by the guide

Total: 9 parquets (4 canonical + 5 auxiliary) — the only such case in the project.

---

## The 4 states of a conv in reconcile

| State | Meaning | Where it is |
|---|---|---|
| `added` | Exists in current, didn't exist in previous | **new** conv |
| `updated` | Exists in both, but current has higher `update_time` or enrichment | conv **changed** |
| `copied` | Exists in both, no change | conv **unchanged** |
| `preserved_missing` | Exists in previous but not in current (gone from the server) | **preserved locally** |

Each run produces counters for these 4 states in `reconcile_log.jsonl`.

---

## Canonical parser terms (ChatGPT Phase 2 — `src/parsers/chatgpt.py`)

### Canonical parquet / `processed`

Parser output in `data/processed/<Source>/`. 4 tables (ChatGPT):
`conversations.parquet`, `messages.parquet`, `tool_events.parquet`,
`branches.parquet`. Schema defined in `src/schema/models.py`. Universal
interface consumed by the descriptive dashboard (Quarto) and by external
qualitative-analysis pipelines.

### Branch

Linear path inside the conv's `mapping`. A conv with no fork has 1 branch (`<conv>_main`).
A conv with a fork (node with ≥2 children) has N branches: main goes from the root to
the fork, each child of the fork starts its own sub-branch with
`parent_branch_id` pointing to the origin. `is_active=True` on exactly 1
branch per conv (the one containing `current_node`). v2 ignored off-path forks —
v3 preserves everything.

### ToolEvent

Row in `tool_events.parquet`. Represents a non-conversational operation:
search (`search`), code execution (`code`), canvas, deep research, image
generation (`image_generation`), citation (`quote` = tether_quote), memory
(`bio`), file_search, computer_use, etc. Each raw msg with `author.role=tool`
becomes a ToolEvent. The corresponding msg does NOT appear in `messages.parquet`
(filtered out — only `role∈{user,assistant}` becomes a Message).

### is_preserved_missing / last_seen_in_server

Canonical Conversation fields derived from raw's `_last_seen_in_server`:
`is_preserved_missing=True` when `_last_seen_in_server` ≠ date of the last
known run in merged (idempotent, independent of `today`). Lets
downstream filter "convs active on the server" vs "preserved locally"
without reimplementing the heuristic.

### Custom GPT vs Project (gizmo_id)

`gizmo_id` in raw mixes two concepts via the prefix:
- `g-p-*` → Project (folder with sources). Goes to `Conversation.project_id`.
- `g-*` (not `g-p-*`) → real Custom GPT. Goes to `Conversation.gizmo_id`.

Empirical: ~1045 convs in projects, ~1 conv with a real Custom GPT (current base).

---

## Visible outputs

### `LAST_CAPTURE.md` / `LAST_RECONCILE.md`

Human-readable snapshot of the last run. Quick glance shows when + counts. Overwritten each run.

### `capture_log.jsonl` / `reconcile_log.jsonl`

Cumulative history, append-only — one line per run. Cannot be reconstructed afterwards (without backdating), so it's written at the moment of each execution.

---

## `data/unified/` — consolidated cross-platform parquets

Output of `scripts/unify-parquets.py`. 11 parquets that concatenate the 10
sources × extractor + manual saves into a cross-platform view:

- 4 canonical: `conversations`, `messages`, `tool_events`, `branches`
- 7 auxiliary: `sources`, `notes`, `outputs`, `guide_questions`,
  `source_guides` (NotebookLM), `project_metadata`, `project_docs`
  (Qwen + Claude.ai)

**Strategy:** concat with `pd.concat` + dedup by composite PK
`[source, conversation_id, ...]` (or `[source, project_id, ...]` for the
project auxiliaries), `keep='last'`. Defense against internal dups
(parsers that emit duplicate rows) + parser-fix propagation.

**Decision:** this project materializes `data/unified/` in-house; external
consumer pipelines (qualitative analysis, etc.) read via `dvc import-url`
from those 11 parquets. This project is the canonical data home; consumers
are read-only.

**Idempotent:** running it 1x or 100x produces byte-for-byte identical files.
If you delete `data/unified/`, just run `scripts/unify-parquets.py`
again. No hidden state.

**Bugs covered:**
- DeepSeek `message_id` int 1-98 local-per-conv → composite PK with
  `conversation_id` disambiguates
- Claude Code subagents reusing parent's `message_id` on `/compact`
  compaction → composite PK resolves
- `project_metadata` without a `source` column in the schema → enriched via
  filename (`qwen_project_metadata.parquet` → `source='qwen'`)

**Helper for the qmds:** `setup_unified_views(con, unified_dir,
sources_filter)` in `src/parsers/quarto_helpers.py` loads the 11
parquets as DuckDB views with optional `WHERE source IN (...)` filter
for subsetting (Web Chat, CLI, RAG). Used by the 4 qmds in
`notebooks/00-overview*.qmd`.

---

## Data profile template (`notebooks/_template.qmd`)

Quarto partial shared by 14 qmds — written once, rendered 14
times with different SOURCE_KEY/COLOR/AUX_TABLES. Structure: 1.x schema
+ sample per canonical table, 2.x coverage/gaps (capture_method, model,
thinking, tokens, latency), 3.x volumes/distributions (timeline, heatmap,
words, tools, lifetime, branches, account), 4.x preservation/states/itable.

Conditionals via `has_col(con, table, col)` — sections only appear if the
platform has the column. Per-account filter via `ACCOUNT_FILTER` in the
per-source qmd config.

**Auxiliary partial:** `_template_aux.qmd` iterates over the
`AUX_TABLES_CONFIG` dict — generates schema/sample/stats for `sources`
(NotebookLM), `notes`, `outputs`, `guide_questions`, `source_guides`,
`project_metadata` (Qwen/Claude.ai), `project_docs`. Configured in
`AUX_TABLES = [...]` in the per-source qmd.

**Helpers:** `src/parsers/quarto_helpers.py` — 11 functions (setup_views_with_manual,
setup_notebook, has_col, has_view, table_count, fmt_pct, fmt_int, safe_int,
show_df, show_md, plotly_bar). 40 tests in `tests/parsers/test_quarto_helpers.py`.

**Per-source qmd:** ~50 lines. Setup (SOURCE_KEY, SOURCE_TITLE, SOURCE_COLOR,
PROCESSED, TABLES, AUX_TABLES, ACCOUNT_FILTER) + `setup_notebook(...)` +
`{{< include _template.qmd >}}` (+ optional `{{< include _template_aux.qmd >}}`).

---

## Fundamental reminder

> **Discovery can go down. Merged cannot.**

If you see discovery dropping, it's because the server changed. If you see merged growing, it's because we captured more history. If you see merged dropping — that's a bug and needs investigation.

---

## ChatGPT server behavior (empirically validated)

### `update_time` on conv rename

The server **bumps `update_time` to the current time** when you rename a chat from the sidebar. Validated 2026-04-28 with 2 old chats (Oct/2025 and May/2025) — both jumped to 2026-04-28 when renamed.

**Implication:** rename is detected by the normal incremental path (`update_time > cutoff` forces refetch). The extra guardrail in code (`_filter_incremental_targets` comparing discovery `title` vs `prev_raw`) is defense in depth in case the behavior changes.

### Project rename

Always detected, regardless of `update_time`. `project_names` is re-fetched every run (via DOM scrape or API). Since `_project_name` is injected into all convs of the project on enrichment, the reconciler detects the change via diff of `_*` fields.

### `/projects` 404 intermittent

Discovery has automatic fallback: `/projects` → `/gizmos/discovery/mine` → DOM scrape of the sidebar. Fail-fast only triggers if ALL fail together (rare). Accepts partial capture only when explicitly used as last resort (and even then, if the capture drops >20% from the historical baseline, it aborts).
