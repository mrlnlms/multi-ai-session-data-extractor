# Agent Memory History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve immutable CLI agent-memory versions with auditable temporal evidence and useful current-state projections.

**Architecture:** Keep `agent_memories` as the logical-document projection and add append-only `agent_memory_versions` plus `agent_memory_temporal_evidence`. Capture writes content-addressed raw versions and an atomic observation manifest; parsing derives all three tables deterministically, including a documented best-effort reconstruction for already preserved material.

**Tech Stack:** Python 3.12, dataclasses, pandas/Parquet, JSON manifests, SHA-256, pytest, DVC-managed `data/`.

**Spec:** `docs/product/agent-memory-architecture.md`

## Global Constraints

- Never delete a previously preserved memory or version.
- Unknown timestamps remain null; every inferred effective timestamp records basis and confidence.
- Preserve pre-existing worktree changes, including the current `docs/ROADMAP.md` edit.
- Do not commit, run `dvc add`, push Git/DVC, or publish without explicit user authorization.
- Claude Code and Codex ship first; other CLI platforms require a separate capability census.

---

### Task 1: Published schema and stable identity

**Files:**
- Modify: `src/schema/models.py`
- Modify: `src/workflows/unify.py`
- Test: `tests/schema/test_agent_memory.py`
- Test: `tests/workflows/test_unify.py`

**Interfaces:**
- Consumes: the existing `AgentMemory` and `agent_memories_to_df` contract.
- Produces: `AgentMemoryVersion`, `AgentMemoryTemporalEvidence`, dataframe helpers, and auxiliary table keys `agent_memory_versions` and `agent_memory_temporal_evidence`.

- [ ] Write failing schema tests proving that `memory_id` includes the full relative path, version IDs include the content SHA-256, confidence accepts only `high|medium|low|unknown`, and empty dataframe helpers retain their schemas.
- [ ] Run `pytest -q tests/schema/test_agent_memory.py tests/workflows/test_unify.py` and confirm the new types/tables are absent.
- [ ] Add `relative_path`, `current_version_id`, `first_seen_at` and `last_seen_at` to `AgentMemory`; add the two dataclasses and dataframe helpers specified in the design document.
- [ ] Add both auxiliary tables to `AUX_TABLE_KEYS` in `src/workflows/unify.py`, keyed by `version_id` and `evidence_id` respectively.
- [ ] Re-run the focused tests and confirm stable column order, uniqueness keys and validation.

### Task 2: Append-only observation manifest and immutable raw versions

**Files:**
- Replace: `src/capture/cli/memory_metadata.py` with a versioned observation-manifest implementation retaining a v1 reader.
- Modify: `src/capture/cli/copy.py`
- Test: `tests/capture/cli/test_memory_metadata.py`
- Test: `tests/capture/cli/test_copy.py`

**Interfaces:**
- Consumes: source roots for `claude_code` and `codex`.
- Produces: `observe_memory_files(raw_root, source_root, source, captured_at) -> MemoryObservationManifest` and immutable files under `raw_root/_memory_versions/<sha256>.md`.

- [ ] Write failing tests for first observation, unchanged re-observation, changed content, disappearance, basename collision in nested Codex paths, atomic manifest replacement and v1 sidecar migration.
- [ ] Run the focused tests and confirm failures describe the missing v2 behavior.
- [ ] Implement canonical `relative_path`, streaming SHA-256, UTC filesystem timestamps, first/last-seen retention and a content-addressed version write that refuses mismatched existing bytes.
- [ ] Change `copy_claude_code` and `copy_codex_memories` to call the observation API after cumulative copy while retaining missing documents and all known hashes.
- [ ] Re-run the focused tests and verify that changing a live file creates a second immutable version rather than overwriting historical query evidence.

### Task 3: Deterministic parser and temporal evidence

**Files:**
- Modify: `src/parsing/agent_memory.py`
- Modify: `src/platforms/claude_code/parser.py`
- Modify: `src/platforms/codex/parser.py`
- Modify: `src/platforms/claude_code/commands/sync.py`
- Modify: `src/platforms/codex/commands/sync.py`
- Test: `tests/parsing/test_agent_memory.py`
- Test: `tests/platforms/claude_code/test_parser_memories.py`
- Test: `tests/platforms/codex/test_parser_memories.py`

**Interfaces:**
- Consumes: the v2 observation manifest and immutable raw versions.
- Produces: current documents, all versions and all temporal-evidence rows on each parser instance.

- [ ] Write failing tests for observed mtime, observed birthtime, first-seen evidence, null unknown creation time, deterministic evidence IDs, confidence ordering and preserved-missing documents.
- [ ] Run the focused tests and confirm the current mtime-to-created-at behavior fails the new contract.
- [ ] Parse every manifest version, emit evidence rows, select effective timestamps with the documented priority function, and project the newest observed version into `agent_memories`.
- [ ] Write all three Parquets from both platform parsers and include their row counts in sync statistics and capture logs.
- [ ] Re-run the focused tests and verify that an effective date can always be traced to its evidence row.

### Task 4: Historical reconstruction

**Files:**
- Create: `src/operations/reconstruct_agent_memory_history.py`
- Test: `tests/operations/test_reconstruct_agent_memory_history.py`
- Modify: `docs/operations/commands.md`

**Interfaces:**
- Consumes: preserved raw memory files, v1 metadata, live-source stat metadata when present, and explicitly supplied Git/DVC revision evidence.
- Produces: a preview report by default and a v2 manifest plus immutable version files only with `--apply`.

- [ ] Write failing tests for dry-run purity, idempotent apply, source-mtime evidence, birthtime evidence, filename timestamp inference, explicit-content timestamp inference and unresolved null dates.
- [ ] Run the operation tests and confirm the command is not implemented.
- [ ] Implement preview-first reconstruction with `--source claude_code|codex`, `--apply`, machine-readable findings and no network access.
- [ ] Require every heuristic inference to emit `is_inference=True`, locator details and confidence; do not inspect prose dates unless the rule matches an explicit documented date declaration.
- [ ] Re-run the tests twice over the same fixture and prove byte-identical manifests and IDs.

### Task 5: Query surfaces and maintained documentation

**Files:**
- Modify: `notebooks/_template_aux.qmd`
- Modify: `docs/extractor-engineering/platforms/cli/claude-code/state.md`
- Modify: `docs/extractor-engineering/platforms/cli/codex/state.md`
- Modify: `docs/extractor-engineering/known-limitations.md`
- Modify: `README.md`
- Test: `tests/reporting/test_quarto_helpers.py`

**Interfaces:**
- Consumes: the three unified agent-memory tables.
- Produces: current-memory, version-history and temporal-confidence views with explicit derived-evidence language.

- [ ] Add failing reporting tests for current version, version count, first/last seen, effective dates, basis and confidence labels.
- [ ] Run the reporting tests and confirm the new fields are not yet exposed.
- [ ] Extend the auxiliary-table template with document, version and evidence sections; do not rank inferred low-confidence dates as equivalent to observed dates.
- [ ] Update maintained docs with capture paths, reconstruction command, temporal semantics, query guidance and remaining inability to prove some historical dates.
- [ ] Run reporting tests, local link checks and `git diff --check`.

### Task 6: Migration validation and publication gate

**Files:**
- Validate only; data outputs remain under the existing DVC contract.

**Interfaces:**
- Consumes: completed Tasks 1-5 and current local Claude Code/Codex evidence.
- Produces: reviewed local raw, processed and unified outputs ready for a separately authorized publication.

- [ ] Run reconstruction in preview mode and review counts by evidence type, confidence, source and unresolved timestamp.
- [ ] After user approval for local mutation, apply reconstruction and run both CLI syncs followed by `python -m src.workflows.unify`.
- [ ] Verify identity uniqueness, version hash integrity, no lost current memories, preserved-missing retention and exact evidence references.
- [ ] Run `.venv/bin/pytest -q`, documentation link checks and `git diff --check`.
- [ ] Stop for explicit review before any commit, `dvc add`, `dvc push` or Git push.
