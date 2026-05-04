# Changelog

All notable changes to this project are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-04

First public release. Coverage status at publication time:

### Web platforms (7) — sync + reconcile + canonical parser v3 + Quarto descriptive

- **ChatGPT** — living reference. Single cumulative folder, 4-stage sync (capture
  + assets + project_sources + reconcile), headed capture (Cloudflare),
  fail-fast against flakey discovery. Covers off-path branches, voice
  (in/out), DALL-E, canvas, deep_research, custom_gpt vs project.
- **Claude.ai** — 3-stage headless sync. Branches via flat DAG, thinking
  blocks, tool_use/result with MCP detection (3 signals), attachments with
  inline extracted_content, queryable project docs.
- **Perplexity** — 2-stage headed sync. Threads + spaces (collections) +
  pages (articles) + artifacts (assets). Pin via `list_pinned_ask_threads`
  POST `{}`, skills via scope-based endpoint, archive Enterprise-only
  (no-op on Pro/free).
- **Qwen** — 2-stage headless sync. 8 chat_types (chat/search/research/
  dalle/etc.), reasoning_content in thinking, t2i/t2v as ToolEvent.
- **DeepSeek** — 2-stage headless sync. R1 reasoning in ~31% of msgs,
  flat DAG branches with heavy regenerate (~2.4 branches/conv).
- **Gemini** — 3-stage multi-account headless sync. Positional schema
  (batchexecute, no named keys) discovered via probe. Pin via
  `c[2]` of MaZiqc listing, search/grounding citations.
- **NotebookLM** — 3-stage multi-account headless sync. 9 parquets (4
  canonical + 5 auxiliaries for sources/notes/outputs/guide_questions/
  source_guides). 9 RPCs mapped. `guide.summary` becomes a system message
  to ensure `message_count >= 1`.

### CLIs (3) — copy + canonical parser v3

- **Claude Code** — copy from `~/.claude/projects/`, sub-agents as
  `interaction_type='ai_ai'`.
- **Codex** — copy from `~/.codex/sessions/`, function_call ↔
  exec_command_end correlated.
- **Gemini CLI** — copy from `~/.gemini/tmp/`, multi-snapshot consolidated
  via dedup by message_id.

### Manual saves (3 parsers)

- `clippings_obsidian` — clippings from the Obsidian extension.
- `copypaste_web` — manual paste from platform UIs.
- `terminal_claude_code` — manually captured terminal outputs.

`Conversation.capture_method` (schema v3.2) distinguishes `extractor` /
`manual_*` / `legacy_*`.

### Cross-platform overview

- `scripts/unify-parquets.py` materializes 11 consolidated parquets in
  `data/unified/` via concat + dedup with composite PK.
- 4 Quarto overviews (`00-overview*.qmd`): general, web, cli, rag.

### Streamlit dashboard

- Automatic platform discovery via `KNOWN_PLATFORMS`.
- Quarto render via subprocess + symlink to `static/quarto/` (no
  disk duplication).
- Stale HTML detection (parquets > last render).

### Canonical schema v3.2

`src/schema/models.py`:

- `Conversation`, `Message`, `ToolEvent`, `Branch` — 4 canonical tables.
- `ProjectMetadata`, `ProjectDoc` — auxiliaries for platforms with projects.
- `NotebookLM*` — 5 specific auxiliaries (sources, notes, outputs,
  guide_questions, source_guides).
- `is_preserved_missing` + `last_seen_in_server` — universal preservation.
- `is_pinned`, `is_archived`, `is_temporary` — cross-platform flags.
- `capture_method` — distinguishes extractor / manual / legacy.

### Principles

- Capture once, never downgrade (single cumulative folder + skip_existing).
- Preservation above all (`_preserved_missing` on convs and sources).
- Fail-fast against flakey discovery (20% threshold).
- The canonical schema is the boundary (extractors/parsers convert; analysis reads
  parquet read-only).

### Tests

- 514 tests passing on Python 3.12 and 3.13.
- Covers all 10 parsers, the canonical schema, notebook helpers, unify, the 7
  web reconcilers (smoke + idempotency), pure functions of the 6 web extractors.

### Documentation

- `docs/SETUP.md`, `docs/CONTRIBUTING.md` (with 8-phase playbook for
  adding a new platform + 10 transferable lessons), `docs/SECURITY.md`,
  `docs/LIMITATIONS.md`, `docs/glossary.md`, `docs/operations.md`.
- `docs/platforms/<plat>/{state,server-behavior}.md` per platform.
- `docs/cross-platform-features.md` — pin/archive/voice/share per
  platform.

### Infrastructure

- GitHub Actions: pytest on Python 3.12 + 3.13 on every push/PR.
- Issue + PR templates.
- pyproject.toml with metadata + dependencies.

[Unreleased]: https://github.com/mrlnlms/multi-ai-session-data-extractor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mrlnlms/multi-ai-session-data-extractor/releases/tag/v0.1.0
