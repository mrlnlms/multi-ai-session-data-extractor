# Contributing

This project accepts contributions — issues, PRs, new platforms,
documentation improvements.

## How to report a problem

1. Check whether the issue is already in [LIMITATIONS.md](LIMITATIONS.md).
   Some things are known limitations (not bugs).
2. Reproduce the issue with the latest code (`git pull`).
3. Open an issue with:
   - Affected platform (e.g., ChatGPT, Claude.ai)
   - Exact command you ran
   - Full error (stderr, traceback)
   - Python version (`python3 --version`)
   - macOS or Linux

For security vulnerabilities, see [SECURITY.md](SECURITY.md).

## How to submit a Pull Request

1. **Fork + branch.** Don't work on `main`.
2. **Run the tests** before submitting:
   ```bash
   PYTHONPATH=. .venv/bin/pytest
   ```
   All 514+ tests must pass.
3. **Add tests** for behavior changes. Patterns in
   `tests/parsers/test_*.py`.
4. **Match the style** of existing code. There is no automated linter;
   follow what's already there.
5. **Commit messages** in Portuguese or English, in conventional commits
   style (`feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`,
   `test: ...`).
6. **Update the documentation** when applicable.

### Before the PR

- [ ] Tests pass (`pytest`)
- [ ] No credentials committed (`git diff` clean)
- [ ] Change documented where appropriate
- [ ] Commits signed with your real name

## Adding a new platform

ChatGPT is the **living reference** — copy the structure, adapt only
what's necessary. Semantic divergence vs ChatGPT requires justification.
Each platform is a ~3-5 day work package.

### Principle

**Replicate, don't reinvent.** Each artifact below has an exact mirror in
ChatGPT — start by copying, adapt only the minimum necessary.

### Generic sequence (8 phases per platform)

#### Phase A — Single cumulative folder (raw)

**Goal:** mutable in-place capture in `data/raw/<Source>/` (no
timestamp).

- Adapt `<source>-export.py` (or equivalent orchestrator) to use a fixed
  `data/raw/<Source>/`.
- `LAST_CAPTURE.md` regenerated each run.
- `capture_log.jsonl` append-only.
- `_find_last_capture` in the extractor's orchestrator.

**Reference:** `src/extractors/chatgpt/orchestrator.py` (`_resolve_output_dir`,
`_find_last_capture`, `_get_max_known_discovery`).

#### Phase B — Sync orchestrator

**Goal:** `scripts/<source>-sync.py` orchestrating capture + assets +
reconcile in N stages (varies by platform).

- Mirror `scripts/chatgpt-sync.py` (4 stages).
- Adapt stages per platform (some don't have separate "project sources",
  others have different asset types).
- Consistent flags: `--no-binaries`, `--no-reconcile`, `--full`,
  `--dry-run`.

**Reference:** `scripts/chatgpt-sync.py`.

#### Phase C — CRUD scenario validation

**Goal:** ensure the "capture once, never downgrade" cycle works
end-to-end.

Empirically test the scenarios applicable to the platform:

- Conv deleted → `is_preserved_missing=True`.
- Conv updated (new message) → `updated`, timestamp bumps.
- New conv → `added`.
- Conv renamed → `updated` (validate whether the server bumps update_time).
- Project created/deleted (if applicable) → preservation in `_files.json`.

Document server behavior in
`docs/platforms/<plat>/server-behavior.md`.

#### Phase D — Empirical findings + fixtures

**Goal:** collect real features before the canonical parser.

- Identify distinctive features (e.g., Claude.ai has thinking blocks +
  MCP integrations; Gemini has Deep Research; NotebookLM has 9 types of
  outputs).
- Extract sanitized fixtures into
  `tests/extractors/<plat>/fixtures/raw_with_*.json`.
- Meta-tests in `test_fixtures_integrity.py` per platform.

**Reference:** 9 ChatGPT fixtures in
`tests/extractors/chatgpt/fixtures/`.

#### Phase E — Canonical parser

**Goal:** parser that delivers 4 parquets in the v3 schema.

- Rewrite `src/parsers/<source>.py` (don't branch the legacy file —
  rewrite in-place; keep backup in
  `_backup-temp/parser-<source>-promocao-<date>/` during validation).
- Canonical schema: `Conversation`, `Message`, `ToolEvent`, `Branch`.
- `branch_id` non-optional (default `<conv>_main` if no fork).
- `is_preserved_missing` + `last_seen_in_server` in Conversation.
- ToolEvents for internal agents/tools (if the platform has them).
- Asset paths as `Optional[list[str]]` (native).

**Reference:** `src/parsers/chatgpt.py` + helpers in `_chatgpt_helpers.py`.

#### Phase F — CLI parse script

**Goal:** `scripts/<source>-parse.py` consuming merged → parquets.

- Reads `data/merged/<Source>/<source_lower>_merged.json`.
- Writes `data/processed/<Source>/{conversations, messages, tool_events,
  branches}.parquet`.
- Idempotent (running it 2x = same bytes).

**Reference:** `scripts/chatgpt-parse.py`.

#### Phase G — Cross-validation vs legacy (if any legacy exists)

**Goal:** document parity of the new vs old parser.

- Run legacy parser (in backup) and new one on the same merged.
- Compare counts (convs, msgs, tool_events).
- Document differences.
- Criterion: new parser ⊇ old parser (can have more — cannot have
  less).

#### Phase H — Descriptive Quarto notebook

**Goal:** `notebooks/<source>.qmd` rendering static HTML in the
"zero-interpretation" pattern.

- Canonical template in `notebooks/_template.qmd` + helpers in
  `src/parsers/quarto_helpers.py`. Per-source qmd has ~50 lines — only
  config (`SOURCE_KEY`, `SOURCE_TITLE`, `SOURCE_COLOR`, `PROCESSED`,
  `TABLES`, `AUX_TABLES`, `ACCOUNT_FILTER`) + `setup_notebook(...)` +
  `{{< include _template.qmd >}}`.
- Platform primary color in `SOURCE_COLOR` (single constant).
- Auxiliary tables: add names to `AUX_TABLES = [...]` + include
  `_template_aux.qmd`.
- Render via `quarto render notebooks/<source>.qmd` in ~20-60s.
- Self-contained HTML ~40 MB (embed-resources).

**Reference:** any of the 14 qmds — `notebooks/codex.qmd` is the smallest
(~49 lines).

### Done criteria

A platform is only "shipped" when:

- ✅ Sync orchestrator functional, idempotent.
- ✅ Single cumulative folder `data/raw/<Source>/`.
- ✅ `LAST_CAPTURE.md` + `LAST_RECONCILE.md` + jsonls updated.
- ✅ Applicable CRUD scenarios empirically validated.
- ✅ Canonical parser generates 4 parquets in the v3 schema.
- ✅ Fixtures + meta-tests cover distinctive features.
- ✅ Quarto notebook renders < 30s, HTML < 100MB.
- ✅ Dashboard reflects the platform automatically.
- ✅ Documentation updated (`docs/platforms/<plat>/state.md` +
  `server-behavior.md`).

### Transferable lessons

Patterns observed when adding previous platforms. Worth reading before
starting:

1. **Network tap > guessing.** Don't guess endpoint URLs. UI name and API
   name diverge (Perplexity: Spaces/collections, Pages/articles,
   Artifacts/assets). Use Playwright `page.on("response")` during real
   manual navigation to capture the actual XHRs.

2. **SSR can hide data.** SPAs with programmatic routing
   (`router.push` on onClick) don't have literal `<a href>`. Solution:
   programmatic DOM-click (`row.click()` + `expect_navigation()`).

3. **Free accounts limit testing.** Pro/Enterprise features may appear
   in the DOM but return 404 or "Upgrade" modal. Document in
   `LIMITATIONS.md` instead of assuming a bug.

4. **Reconciler must cover divergent delete scenarios.** "Delete" can
   behave differently: thread disappears from everything (`ENTRY_DELETED`
   in all listings) vs disappears from global listing but remains
   referenced in some container (passive orphan). Mark **both** as
   preserved.

5. **Discovery file naming.** Raw and merged may have different names
   for the same concept. Reconciler must try both names, not fail
   silently.

6. **Server bumps update_time on rename.** Empirically in ChatGPT,
   Perplexity, Qwen, DeepSeek. Normal incremental path covers it — no
   special detection needed. Extra guardrail (compare title vs
   prev_raw) helps as defense in depth.

7. **Manifest with status for idempotency.** Old uploads can be
   irrecoverable (S3 cleanup, parents deleted). Marking entries as
   `failed_upstream_deleted` avoids retrying every run.

8. **Positional vs named schema.** Some APIs use positional structures
   (Gemini batchexecute: `turn[3][0][0][1]`). Document indexes
   exhaustively in `<plat>-probe-findings.md`.

9. **Speculative plan turns into refactor.** Exploring real data before
   formal planning saves work. Sequence: basic sync → interactive
   exploration (60-90 min) → identify features → fixtures → parser.

10. **Don't branch files.** Established pattern: rewrite in-place.
    Backup in `_backup-temp/` during cross-validation. When parity is
    confirmed, delete the backup.

### Already-mapped specifics

When starting on an existing platform (e.g., extending Claude.ai), check
first:

- `docs/platforms/<plat>/state.md` — current coverage.
- `docs/platforms/<plat>/server-behavior.md` — observed upstream
  behavior.
- `docs/cross-platform-features.md` — cross checks (pin, archive, voice,
  share).

## Project conventions

### Language

- **Code:** English (function, variable, class names).
- **Comments and docs:** Portuguese or English — be consistent within a
  file.
- **Commit messages:** Portuguese or English.

### Code style

- Type hints where they help (not required everywhere).
- Docstrings on public functions and in cases with non-obvious logic.
- `from __future__ import annotations` at the top of new modules.
- No configured linter — follow the style of existing files.

### Tests

- `tests/` mirrors `src/` (`tests/parsers/test_<X>.py` for
  `src/parsers/<X>.py`).
- Use sanitized fixtures in `tests/extractors/<plat>/fixtures/` to test
  parsing — **do not commit real personal data**.
- Tests must run in <5s total. If a test is slow, either it needs to be
  broken up, or justify it in the docstring.
- **Tests never regress.** Each added platform must **increase** the
  number of tests in the suite, not decrease it.

### Canonical schema

`src/schema/models.py` defines the structure — `Conversation`, `Message`,
`ToolEvent`, `Branch`. Schema changes are **breaking changes** —
discuss in an issue before proposing a PR.

Current schema: v3.2 (introduced `capture_method` in Conversation).

### Non-negotiable principles

1. **Capture once, never downgrade.** Single cumulative folder +
   `skip_existing` in the downloaders.
2. **Preservation above all.** Conversations/files deleted on the server
   remain locally with `is_preserved_missing=True`.
3. **The canonical schema is the boundary.** Platform-specific quirks
   don't leak into the analysis stage.
4. **Fail-fast against flaky discovery** — discovery <80% of history
   aborts before save.

## Where to find context

- [README.md](../README.md) — overview.
- [docs/README.md](README.md) — documentation index.
- [docs/glossary.md](glossary.md) — project terms.
- [docs/platforms/](platforms/) — `state.md` + `server-behavior.md` per
  platform.
- [docs/cross-platform-features.md](cross-platform-features.md) — pin,
  archive, voice, share per platform.

## Expected behavior

Issues and PRs will be reviewed when the maintainer has time. There is
no SLA. For large changes, open a discussion issue before investing
time in code.

If the contribution doesn't fit the project scope (e.g., interpretive
analysis features — sentiment, clustering, topic detection — which
explicitly do not belong here), it may be closed without merging.
Discussing early avoids rework.
