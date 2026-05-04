# Known limitations

Honest list of what **does not work** or **has not been validated**. Updated
on 2026-05-04.

Limitations fall into 3 categories:

- **Upstream** — the platform doesn't expose the feature; nothing we
  can do on our side.
- **Additional pending coverage** — the feature exists but needs
  mapping work (live probe on the platform).
- **Test coverage** — the code works empirically but there are gaps
  in automated testing.

## Per platform

### ChatGPT

- **Voice — 97% of transcripts already captured via Pass 1.** 127 of 131
  voice messages have transcript text populated (via raw heuristic
  detecting `audio_transcription` in parts). 4 voice messages end up
  with empty text (edge cases — transcription failed upstream). The Pass 2
  via DOM scraping (`src/extractors/chatgpt/dom_voice.py`) exists but
  is not necessary for this coverage — over-engineering for the 4
  remaining cases.
- **8 unrecoverable assets:** some old assets are no longer
  available on the server (parents were deleted). Documented as
  "failed=8" in the download — not a bug.

### Claude.ai

- **`is_archived` — always None:** Claude.ai does not expose this field on
  any visible endpoint. To distinguish "not archived" from
  "information not available", the parser uses `None` instead of `False`.

### Perplexity

- **Archive — Enterprise-only:** the backend accepts the
  `archive_thread`/`unarchive_thread` requests on Pro accounts (200 success), but
  the archived state **is not exposed** on any listing visible on
  Pro/free. Listing archived threads only works on Enterprise accounts
  (gated by Cloudflare Access). For Pro accounts, archive is an observable
  no-op — not an extractor gap.
- **Voice on Perplexity** — the server transcribes and discards the audio,
  with no `is_voice` in the schema. There's no way to tell retroactively whether a
  message was originally voice.
- **Old attachments on S3 expire.** Perplexity does automatic cleanup
  of old uploads on S3. The manifest preserves the entries
  as `failed_upstream_deleted` for idempotency (skip on re-runs).
  Equivalent to the 8 old ChatGPT assets with deleted parents.
- **Page slugs are not in the initial DOM.** Perplexity is a Vite SPA with
  programmatic router (`router.push` on onClick). Pages require a
  programmatic DOM-click with `expect_navigation` to extract slugs. Cost: ~10s
  per page. Acceptable for low volumes.
- **1 orphan thread on GAS:** thread `d344c501` is referenced in a
  space but was deleted from the server. Preserved locally as
  `is_preserved_missing=True`.

#### Pro/Max features not covered (public TODO for contributors)

These validations require a Pro Max account and remain open until someone tests:

- **Computer mode (`mode=asi`)** — endpoint `/rest/spaces/{uuid}/tasks`
  returns `{tasks: []}` on a Pro account. On Max: create a Computer task and
  capture generated threads + stored tasks + possible new
  endpoints `/rest/computer/*`.
- **Scheduled tasks** — "Scheduled" button on the home. On Max: create
  a schedule and discover the endpoint.
- **Model council (Max tier)** — Max feature consults multiple models
  simultaneously. Schema unknown. Capture each model as
  a separate ToolEvent? Aggregate into a single assistant message?
- **Alternative AI models in the listing** — Sonar / GPT / Gemini / Claude
  / Kimi etc. Locked on Pro. On Max: switch model in the thread and validate
  `display_model` in the entry.
- **Pages — create one of your own.** Today we capture bookmarked pages. On
  Pro: publish a thread AS a Page and discover the slug + schema of the
  generated article + differences vs. bookmarked pages.
- **Modern Deep Research.** Mode locked on Pro. On Max: validate whether
  mode in the entry comes as `COPILOT` (legacy) or has a new name
  (`DEEP_RESEARCH`); whether the entry has extra fields (multi-step, expanded
  citations).

### Qwen

- **Archive — upstream no-op:** the server accepts the request but the
  `archived` flag never persists; `archived=True` never appears in listings.
  Same pattern as Perplexity — not an extractor gap.
- **Temporary chats:** Qwen does not have this feature. The `is_temporary`
  field stays `None`.
- **`/v2/chats/archived` always returns empty** even after archive
  request. Documented.

### DeepSeek

- **`is_archived` and `is_temporary` — always None:** DeepSeek does not expose
  these features. None pattern (not False) to make it clear.
- **`message_id` is local-per-conv INT (1-98):** not a global UUID. For
  cross-platform consolidation, `unify-parquets.py` uses composite PK
  `[source, conversation_id, message_id]`.

### Gemini

- **Drafts/alternative regenerate:** when you regenerate a response,
  the previous state stays in `turn[1]` but parser v3 does not capture it — only
  the active state. (Backlog: implement when a representative real
  case appears.)
- ~~**Search/grounding citations**~~ **CLOSED 2026-05-04**: tool events
  of type `search_result` are created (1 per citation with URL, title,
  snippet, favicon, deduplicated by URL). They also populate
  `Message.citations_json` in the messages parquet. Current base: 416
  search results across 9 messages that used Deep Research.
- **Share URL:** Gemini allows sharing a conversation via public URL.
  This state is not recorded in the conversation body (the server generates the
  URL and keeps it isolated). Not an extractor gap — not capturable.
- **Multi-account:** support for 2 Google accounts is hardcoded (acc-1, acc-2).
  For more accounts, you would need to adjust `gemini-sync.py` and the
  Quarto template.

### NotebookLM

- **No pin feature** upstream — `is_pinned` field stays `None`.
- **`update_time` in the listing is volatile** — the server reindexes
  periodically and bumps the timestamp without an actual content change. The
  reconciler uses semantic hash (not timestamp) to decide refetch —
  behavior already mitigated by design.
- **Mind map — 75 of 141 with full tree.** The hierarchical tree
  (root + recursive children) is downloaded by the extractor at
  `data/raw/NotebookLM/account-{N}/assets/mind_maps/<nb>_<mm>.json` and
  populated in `notebooklm_outputs.parquet` `content` field (up to 75KB
  of hierarchy). The remaining 66 mind maps end up with metadata only
  because the asset wasn't downloaded (upstream regenerate or download
  failure — not blocking).
- **Real chat — not a bug, it's the state of the data.** Of the 143 current
  notebooks, 0 have chat populated upstream (the user did not have real
  chats in the notebooks). The 138 captured messages are `role=system`
  (`guide.summary` becoming seq=0). When you have real chats in the
  future, the parser has a placeholder in `_extract_chat_turns()` — it may
  need to map the positional schema.

### Claude Code (CLI)

- **No pin/archive/temporary features** — these are CLIs, no server
  with those semantics. The fields stay `None`.
- **No dedicated reconciler:** file preservation is done by
  `cli-copy.py` (never deletes destination). The parser detects
  `is_preserved_missing=True` by comparing `data/raw/Claude Code/` with
  current `~/.claude/projects/`.
- **Compacted sessions (`/compact`):** when you use `/compact`, the
  thread continues in a new JSONL. The parser identifies and consolidates via
  internal `sessionId` (all JSONLs become 1 Conversation with
  `conv_id` = root of the chain).

### Codex (CLI)

- Same observations as the CLIs above.

### Gemini CLI

- Same observations as the CLIs above.
- **Periodic snapshots:** Gemini CLI writes multiple
  `session-<timestamp>-<sid>.json` files for the same session. The parser
  consolidates via `sessionId` with dedup by `message_id`.

## Test coverage

- **514 tests passing.** Covers parsers (all 10), the canonical schema,
  notebook helpers, unify, **reconcilers for all 7 web platforms**
  (smoke tests with fixtures: build_plan + run_reconciliation +
  preservation + idempotency), **pure functions of the 6 web extractors**
  (parsing, dedup, discovery baseline, target_path, ext_from_url).
- **CI runs on Ubuntu + macOS x Python 3.12/3.13** (4 unit
  combinations) + integration smoke (Quarto render + Playwright import + Streamlit
  healthcheck + 10 platform imports).
- **Extractors' HTTP/auth/Playwright without unit tests.** The logic
  is validated empirically in real syncs. Mocking Playwright/httpx is
  expensive (~20h of setup + fragile when the platform changes). If worth it,
  on the v1.0 backlog.

## Environment coverage

- **Languages tested:** en + pt-BR (NotebookLM acc-1/acc-2,
  Gemini acc-1/acc-2). Other languages may have UI strings hardcoded in
  probes (e.g. "Deep Dive" / "Aprofundar" in NotebookLM) that haven't been
  exercised. When that comes up, it's a targeted fix.
- **Account tiers tested:** Free / Pro. Enterprise / Team / Max not
  validated (see Perplexity Pro/Max above as a concrete example). The canonical
  schemas have the generic fields; fine-tuning when a contributor
  with a higher tier tests.
- **Volume validated:** confirmed up to ~140k messages (Claude Code) /
  ~1.2GB raw (NotebookLM acc-1). Above ~500k messages, parsers that
  load everything in memory may need chunked streaming
  (`pyarrow.ParquetWriter` in a loop instead of `to_parquet` directly). Not
  the current case; refactor when someone reports it.

## Operational limitations

- **Windows not tested.** macOS and Linux work.
- **Python ≥3.12 required** (tested on 3.12 and 3.14).
- **Headless capture (no window)** works on Claude.ai, Gemini,
  NotebookLM, Qwen, DeepSeek. ChatGPT and Perplexity require a visible
  window because Cloudflare detects headless clients and blocks them with
  HTTP 403.
- **Profile/cookies** live at `.storage/<plat>-profile-<account>/`. This
  directory is gitignored — never committed. If you delete it, you need to
  redo the login.
- **Multi-account:** only Gemini (2 accounts) and NotebookLM (up to 3 accounts)
  have explicit support. Other platforms: 1 account per installation.
