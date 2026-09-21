# Account Identity Migration Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current session. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents, create commits, modify DVC-managed data, publish, or run `dvc push` in this execution.

**Goal:** Make `account_id` the only durable account identity, preserve every existing UUID and archive, migrate account-owned paths to UUIDs, and publish a catalog-derived analytical account dimension without `technical_key`.

**Architecture:** Catalog version 2 removes `technical_key` and adds optional `display_name` and `email`. Version 1 is accepted only by a dedicated compatibility/migration boundary; normal v2 execution resolves the local browser profile through the existing UUID binding and resolves durable raw/merged paths directly from the UUID. A preview-first migration operation validates legacy-to-UUID path moves and emits the v2 catalog only when the complete migration can be applied safely.

**Tech Stack:** Python 3 dataclasses, pathlib, argparse, pandas/Parquet, pytest, DVC-managed data (read-only during this implementation).

**Spec:** `docs/product/account-architecture.md`, with the decisions supplied by the user on 2026-09-21.

## Global Constraints

- `account_id` is the only canonical account identity and existing UUID values must not change.
- `technical_key` is migration-only compatibility and is absent from the v2 catalog, normal runtime model, and `accounts.parquet`.
- Browser `profile_key` remains installation-local state addressed through the UUID binding.
- Durable per-account raw/merged paths use `account-<account_id>`.
- `display_name` is editable and optional; `email` is optional; presentation falls back to platform plus email when no display name exists.
- CLI/manual fact rows retain null `account_id` when no durable evidence exists.
- Do not modify `data/`, DVC pointers/cache, `.storage/`, or the private registry during this implementation.
- Do not publish, commit, push, or run `dvc push`.

## Implementation status — 2026-09-21

- Catalog v2, metadata editing, v1 migration reader, preview/apply migrator,
  UUID/profile runtime separation, UUID parser resolution, Gemini derived-ID
  preservation, and `accounts.parquet` are implemented.
- Full suite after the applied migration and real-data parser rebuild: 1328
  passed.
- The real-tree preview completed successfully on 2026-09-21: catalog v1 to
  v2, all 19 UUIDs preserved, and 133 path moves proposed with no collision or
  validation error. The preview did not modify `data/`, DVC, or `.storage/`.
- The migration was applied locally on 2026-09-21. All nine web parsers rebuilt
  successfully from UUID paths, `unify` produced 19 unique account rows, and
  every non-null factual `account_id` resolves to the account dimension.
- The parser rebuild also refreshed append-only semantic appearance state in
  `data/assets`; no cleanup command was run.
- The seven affected DVC pointers (`raw`, `accounts`, `merged`, `processed`,
  `unified`, `assets`, and the NotebookLM historical snapshot) were updated
  locally after validation. `dvc status` reports the data and pipelines as up
  to date; publication, commit, push, and `dvc push` have not been run.
- The final pre-commit review corrected maintained setup/pipeline examples that
  still selected accounts through legacy profile locators. Canonical operator
  documentation now routes durable execution through `account_sync ACCOUNT_ID`;
  the full suite still passes with 1328 tests.
- DVC publication completed on 2026-09-21 after the local pointer and test
  gates: 76 missing cache objects were pushed to the configured Google Drive
  remote. Git commit and push remain the final publication steps.

---

### Task 1: Versioned canonical catalog

**Files:**
- Modify: `src/account_catalog.py`
- Modify: `src/account_service.py`
- Test: `tests/test_account_catalog.py`
- Test: `tests/test_account_service.py`

**Interfaces:**
- Produces: `AccountCatalogRecord(account_id, platform, display_name, email, lifecycle_status, created_at, updated_at)`.
- Produces: strict v2 serialization without `technical_key` and a separate `LegacyAccountCatalog` reader used only by migration/compatibility code.
- Produces: account creation/update services keyed only by UUID, including editable `display_name` and optional `email`.

- [ ] Write tests proving v2 round-trips, rejects extra fields including `technical_key`, preserves UUID/timestamps, and validates optional text/email values.
- [ ] Write tests proving v1 can be loaded only through the explicit legacy reader and cannot be serialized as the canonical model accidentally.
- [ ] Implement the v2 model, validation, deterministic serialization, and legacy reader.
- [ ] Update create/lifecycle/metadata mutations to reconstruct v2 records without a technical key.
- [ ] Run `pytest tests/test_account_catalog.py tests/test_account_service.py -q`.

### Task 2: Preview-first UUID layout migration

**Files:**
- Create: `src/operations/migrate_account_identity.py`
- Create: `tests/operations/test_migrate_account_identity.py`
- Modify: `docs/operations/commands.md`

**Interfaces:**
- Consumes: v1 legacy catalog records and current raw/merged/external trees.
- Produces: a deterministic migration plan mapping each legacy path to `account-<account_id>` and a v2 catalog with unchanged UUIDs.
- Produces: `python -m src.operations.migrate_account_identity` preview; `--apply` performs only prevalidated atomic renames and catalog replacement.

- [ ] Test default-root, `account-N`, custom-key, historical archive, already-migrated, missing-tree, collision, and rollback-before-catalog-write cases.
- [ ] Implement discovery without scanning unrelated backend/data surfaces.
- [ ] Implement byte/path collision checks: identical destination is accepted, divergent destination aborts, and no source is deleted merely because it is absent.
- [ ] Implement apply ordering so the v2 catalog is written last and UUIDs remain byte-for-byte identical.
- [ ] Document preview/apply boundaries and the prohibition on automatic DVC/publication actions.
- [ ] Run `pytest tests/operations/test_migrate_account_identity.py -q` using temporary directories only.

### Task 3: UUID-native inventory, bindings, and operator services

**Files:**
- Modify: `src/accounts.py`
- Modify: `src/account_identity.py`
- Modify: `src/account_service.py`
- Modify: `src/operations/accounts.py`
- Modify: `src/application/accounts.py`
- Modify: `dashboard/views/accounts.py`
- Test: `tests/test_accounts.py`
- Test: `tests/test_account_identity.py`
- Test: `tests/operations/test_accounts.py`
- Test: `tests/application/test_accounts.py`
- Test: `tests/test_dashboard_accounts.py`

**Interfaces:**
- Produces: UUID path helpers and UUID-directory parsing; no normal lookup by `(platform, technical_key)`.
- Preserves: `AccountBinding(account_id, profile_key, updated_at)` and auth health keyed by UUID.
- Produces: create/edit UI and CLI fields for `display_name` and optional `email`, with deterministic presentation fallback.

- [ ] Replace inventory joins with UUID joins for v2 paths/catalog records.
- [ ] Keep legacy evidence discovery behind an explicit v1 compatibility adapter so it disappears after migration.
- [ ] Change account creation to require platform plus presentation metadata, generating UUID before any durable path exists.
- [ ] Add metadata-edit preview/apply behavior without changing lifecycle or bindings.
- [ ] Update presentation labels and remove technical-key terminology from normal UI.
- [ ] Run the focused account/application/dashboard tests listed above.

### Task 4: Nine web sources and parsers

**Files:**
- Modify: `src/platforms/{chatgpt,claude_ai,gemini,notebooklm,qwen,deepseek,perplexity,grok,kimi}/commands/{login,sync,parse}.py` as applicable.
- Modify: source-local auth/orchestrator helpers only where they currently derive a profile or durable path from the same argument.
- Modify: the nine maintained `docs/extractor-engineering/platforms/web/*/state.md` files when their documented commands/layouts change.
- Test: existing source command/parser tests plus new UUID-layout cases.

**Interfaces:**
- Consumes: `account_id` plus catalog/binding for login/sync; binding supplies local `profile_key` only to browser auth.
- Produces: raw/merged writes under `account-<UUID>` and parsed fact rows stamped from that UUID directory.
- Compatibility: deprecated legacy selection is accepted only with a v1 catalog and emits an explicit warning; it is rejected with v2.

- [ ] Read each source `state.md` before changing its commands or parser.
- [ ] Convert login/sync selection to UUID while retaining profile binding separation.
- [ ] Convert raw/merged path construction to UUID for all nine sources.
- [ ] Convert parsers to derive account provenance directly from UUID directory names; keep null identities only for documented CLI/manual cases.
- [ ] Cover default, numbered, custom, and historical layouts without platform-specific fixed account counts.
- [ ] Run the focused command/parser/reconciler tests for all nine web sources.

### Task 5: Analytical accounts dimension and integrity

**Files:**
- Modify: `src/schema/models.py`
- Modify: `src/workflows/unify.py`
- Modify: `tests/workflows/test_unify.py`

**Interfaces:**
- Produces: `accounts.parquet` columns `account_id`, `source`, `platform`, `display_name`, `email`, `lifecycle_status`, `created_at`, `updated_at`.
- Enforces: unique UUID primary key and rejection of every non-null factual `account_id` absent from the dimension.

- [ ] Add schema tests for UUID, nullable presentation metadata, lifecycle, and timezone-aware timestamps.
- [ ] Generate the dimension directly from the catalog, including accounts with no facts and historical accounts.
- [ ] Reject orphan factual UUIDs while preserving legitimate null CLI/manual UUIDs.
- [ ] Prove deterministic output and absence of `technical_key`, bindings, profile paths, auth health, and credentials.
- [ ] Run `pytest tests/workflows/test_unify.py -q` using temporary Parquets only.

### Task 6: Contract documentation and final verification

**Files:**
- Modify: `docs/product/account-architecture.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/operations/commands.md`
- Modify other maintained README/schema surfaces only when searches show an outdated canonical fact.

**Interfaces:**
- Produces: one consistent description of v2 identity, finite migration compatibility, 16 unified tables, and publication remaining a separate authorized step.

- [ ] Update maintained docs to distinguish implemented code from an unapplied DVC data migration.
- [ ] Search maintained code/docs for old claims that `technical_key` is canonical or that raw/merged paths are governed by it.
- [ ] Run the focused account, nine-source, schema, and unify suites.
- [ ] Run the full suite because the public schema and every web source are affected.
- [ ] Run local-link validation if provided by the repository and `git diff --check`.
- [ ] Inspect `git status --short` and confirm no files under `data/`, `.dvc/cache/`, or `.storage/` changed.
