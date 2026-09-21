# Account Inventory UUID De-duplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents, alter DVC-managed data, commit, publish, push, or run `dvc push` without a new explicit user authorization.

**Goal:** Make the observable Accounts inventory emit one `AccountState` per canonical UUID while retaining lossless, independently reported local evidence.

**Architecture:** In catalog v2, `discover_accounts()` will collect evidence in UUID-keyed buckets. A local binding maps a UUID to its installation-local `profile_key`; it is used only to attach a profile directory and registry evidence to that UUID. UUID raw/merged directories attach directly, including UUID paths not yet present in the catalog. Evidence with no explicit UUID remains observable as an unclassified entry with `account_id=None`; it never receives a synthetic canonical identity. Version-1 catalog behavior stays behind the existing finite legacy branch.

**Tech Stack:** Python 3 dataclasses and `pathlib`, pytest, Streamlit `AppTest` or an equivalent UI-neutral view-model fixture.

**Spec:** `private/docs/discussions/account-front-state-baseline-2026-09-21.md`; `docs/product/account-architecture.md`; this plan addresses the concrete post-migration dashboard regression observed on 2026-09-21.

## Global Constraints

- `account_id` is the only canonical account identity; do not introduce `technical_key`, profile names, registry labels, or an alias field as a replacement identity in the v2 runtime contract.
- Catalog v2 records and UUID durable raw/merged directories are authoritative identity evidence; local bindings map UUID to a profile locator only.
- Retain unknown local evidence as an observable `Unclassified` entry when it cannot be matched explicitly. Its v2 `account_id` is `None`; do not synthesize a second UUID from a profile, label, email, browser state, or authentication state.
- Preserve catalog-only active/historical entries and historical external evidence.
- Keep v1 support finite and isolated through `AccountCatalog.requires_identity_migration`; do not change the v2 catalog schema, generated Parquets, DVC pointers, `.storage/`, or raw/merged data for this fix.
- Dashboard code remains presentation-only; discovery and merging stay in `src/accounts.py`.
- Validate with temporary fixtures before any optional real-local dashboard smoke check. Do not run capture, parser, unify, migration, DVC, Git commit, or Git push commands.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/accounts.py` | Collect local evidence, resolve explicit UUID relationships, and produce one immutable `AccountState` per observable identity. |
| `tests/test_accounts.py` | Verify v2 UUID consolidation and the non-inference behavior for unmatched local evidence. |
| `tests/application/test_platforms.py` | Verify `load_platform_state()` preserves the consolidated inventory boundary supplied to the dashboard. |
| `tests/test_dashboard_accounts.py` | Verify Accounts presentation receives one row/action target per UUID rather than duplicating a catalog record. |
| `dashboard/views/accounts.py` | Expected to remain unchanged unless the focused UI test exposes a presentation-only defect after discovery is fixed. |

### Task 1: Specify the v2 evidence-consolidation boundary

**Files:**
- Modify: `tests/test_accounts.py`
- Test: `tests/test_accounts.py::test_v2_discovery_consolidates_catalog_binding_profile_and_uuid_paths`
- Test: `tests/test_accounts.py::test_v2_unbound_profile_remains_unclassified_without_aliasing_catalog_account`
- Test: `tests/test_accounts.py::test_v2_unknown_uuid_path_preserves_its_explicit_identity`
- Test: `tests/test_accounts.py::test_v2_historical_archive_joins_its_preserved_catalog_uuid`

**Interfaces:**
- Consumes: `discover_accounts(platform, storage_root, raw_root, merged_root, catalog_path, bindings_path, registry_path)`.
- Produces: exactly one `AccountState` for a catalog UUID that has an explicit binding, profile directory, and `account-<UUID>` raw/merged directories.
- Preserves: unmatched profile/data evidence as a separate `AccountState` with `lifecycle_status is None`; its presence never changes the lifecycle of a catalog record.

- [x] **Step 1: Add a v2 fixture with one explicit UUID identity.**

  In `tests/test_accounts.py`, add helpers that write a version-2 catalog record and an account binding. Use a fixed UUID so the durable directory names are unambiguous:

  ```python
  account_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
  catalog_path.write_text(json.dumps({
      "version": 2,
      "accounts": [{
          "account_id": account_id,
          "platform": "ChatGPT",
          "display_name": "Primary",
          "email": "primary@example.test",
          "lifecycle_status": "active",
          "created_at": "2026-09-21T00:00:00Z",
          "updated_at": "2026-09-21T00:00:00Z",
      }],
  }))
  bindings_path.write_text(json.dumps({
      "version": 1,
      "bindings": [{
          "account_id": account_id,
          "profile_key": "default",
          "updated_at": "2026-09-21T00:00:00Z",
      }],
  }))
  ```

- [x] **Step 2: Write the failing consolidation test.**

  Create `.storage/chatgpt-profile-default`, `raw/ChatGPT/account-<UUID>`, and `merged/ChatGPT/account-<UUID>`. Call `discover_accounts()` with all temporary roots and assert the complete result, rather than indexing a possibly duplicated map:

  ```python
  assert len(states) == 1
  account = states[0]
  assert account.account_id == account_id
  assert account.key == account_id
  assert account.label == "Primary"
  assert account.lifecycle_status is LifecycleStatus.ACTIVE
  assert account.evidence.profile_path == profile
  assert account.evidence.raw_path == raw_account
  assert account.evidence.merged_path == merged_account
  ```

- [x] **Step 3: Write the failing non-inference test.**

  Add an additional unbound profile directory named `.storage/chatgpt-profile-default` to the same fixture. This deliberately reproduces the collision where `legacy_account_id("ChatGPT", "default")` is the preserved catalog UUID. Assert that the catalog UUID remains exactly once and that the second state is unclassified without a synthetic UUID:

  ```python
  assert list(state.account_id for state in states).count(account_id) == 1
  unclassified = next(state for state in states if state.account_id is None)
  assert unclassified.lifecycle_status is None
  assert unclassified.evidence.profile_path == unbound_profile
  canonical = next(state for state in states if state.account_id == account_id)
  assert canonical.evidence.profile_path == profile
  ```

- [x] **Step 4: Cover explicit UUID evidence and the migrated historical archive.**

  Add one test showing that an unknown `account-<UUID>` raw path emits that UUID with `lifecycle_status is None`. Add tests showing that both a NotebookLM `account-<UUID>` archive and a legacy-named archive whose established UUID already exists in the v2 catalog join that catalog state instead of producing a duplicate.

- [x] **Step 5: Run the new tests and confirm they fail against the current duplicate-key implementation.**

  Run:

  ```bash
  .venv/bin/pytest -q \
    tests/test_accounts.py::test_v2_discovery_consolidates_catalog_binding_profile_and_uuid_paths \
    tests/test_accounts.py::test_v2_unbound_profile_remains_unclassified_without_aliasing_catalog_account \
    tests/test_accounts.py::test_v2_unknown_uuid_path_preserves_its_explicit_identity \
    tests/test_accounts.py::test_v2_historical_archive_joins_its_preserved_catalog_uuid
  ```

  Expected: the first test reports two states for the same UUID, because the existing discovery set contains both `default` and the UUID directory suffix.

### Task 2: Consolidate v2 discovery by canonical UUID

**Files:**
- Modify: `src/accounts.py:discover_accounts`
- Test: `tests/test_accounts.py::test_v2_discovery_consolidates_catalog_binding_profile_and_uuid_paths`
- Test: `tests/test_accounts.py::test_v2_unbound_profile_remains_unclassified_without_aliasing_catalog_account`

**Interfaces:**
- Consumes: `AccountCatalog.records`, `AccountBindings.get(account_id)`, profile directories, UUID durable directories, registry data, and auth health observations.
- Produces: v2 `AccountState.key == AccountState.account_id` for each catalog or UUID-path account; `AccountEvidence` aggregates all matched evidence. Evidence without an explicit UUID has `account_id=None` and retains its observed locator only in `key`.
- Compatibility: a v1/missing catalog continues to use the existing key-based legacy discovery path and `legacy_account_id(platform, key)` only for evidence that predates explicit UUID identity.

- [x] **Step 1: Split `discover_accounts()` at the existing migration boundary.**

  Keep the current key-based path only when `catalog.requires_identity_migration` is true or the catalog is empty. For a non-empty v2 catalog, build these explicit indexes before scanning storage:

  ```python
  records_by_id = {
      record.account_id: record
      for record in catalog.records
      if record.platform == platform
  }
  bound_id_by_profile_key = {
      binding.profile_key: account_id
      for account_id, record in records_by_id.items()
      if (binding := bindings.get(account_id)) is not None
  }
  ```

  Do not derive `bound_id_by_profile_key` from registry entries or path labels. If two bindings claim one profile key, reject the ambiguity with a clear `ValueError` rather than silently merging two UUIDs.

- [x] **Step 2: Aggregate v2 evidence in UUID-keyed buckets.**

  Initialize a bucket for every `records_by_id` item so catalog-only active and historical accounts survive. When scanning profiles or registry entries, attach them only through `bound_id_by_profile_key`. When scanning `account-<suffix>` raw/merged paths, attach them by `suffix` whenever it is a canonical UUID; an unknown UUID remains visible with no lifecycle. Use a small mutable local accumulator or an internal helper; keep the public `AccountEvidence` dataclass frozen.

  The emitted construction must have this v2 shape:

  ```python
  states.append(AccountState(
      platform=platform,
      key=account_id,
      label=record.display_name or record.email,
      evidence=AccountEvidence(**bucket),
      authentication=authentication,
      account_id=account_id,
      lifecycle_status=record.lifecycle_status,
      authentication_method=authentication_method,
  ))
  ```

- [x] **Step 3: Preserve unmatchable evidence without treating it as a v2 alias.**

  For an unbound profile, an unsuffixed legacy tree, a non-UUID legacy directory, or registry-only evidence, emit an unclassified state with `account_id=None`. Never look up a v2 catalog record by that observed key. For a historical external archive, join it only when its already-established deterministic archive UUID is present in the v2 catalog; otherwise keep it unclassified with `account_id=None`.

- [x] **Step 4: Keep ordering deterministic and lifecycle/auth semantics unchanged.**

  Sort v2 UUID states by UUID and unmatched evidence after them by observed key. Continue reading auth health strictly by non-null emitted `account_id`; continue reporting `unknown` only when a profile is present and no explicit health observation exists. Exclude v2 evidence with `account_id=None` from runnable account targets.

- [x] **Step 5: Run the focused discovery suite.**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_accounts.py
  ```

  Expected: both new tests pass, as do the existing v1, historical archive, disabled lifecycle, and runnable-profile tests.

### Task 3: Prove the application and Accounts view receive no duplicate action target

**Files:**
- Modify: `tests/application/test_platforms.py`
- Modify: `tests/test_dashboard_accounts.py`
- Test: `tests/application/test_platforms.py::test_platform_state_exposes_one_v2_account_for_catalog_binding_and_uuid_data`
- Test: `tests/test_dashboard_accounts.py::test_account_rows_emit_one_row_per_canonical_uuid`
- Test: `tests/test_dashboard_accounts.py::test_unclassified_evidence_is_visible_but_not_an_action_target`

**Interfaces:**
- Consumes: `load_platform_state("ChatGPT")`, which delegates discovery with project-root constants, and `_account_rows(states)`.
- Produces: one UI inventory row for a canonical UUID with combined profile/raw/merged evidence.
- Does not produce: Streamlit mutations, capture actions, catalog writes, or a deduplication layer in `dashboard/views/accounts.py`.

- [x] **Step 1: Add an application-boundary regression test.**

  In `tests/application/test_platforms.py`, monkeypatch `STORAGE_ROOT`, `DATA_RAW`, `DATA_MERGED`, and `DATA_ACCOUNTS` to temporary roots. Write the same v2 catalog, binding, profile, and UUID raw/merged directories as Task 1. Assert:

  ```python
  state = platforms.load_platform_state("ChatGPT")
  assert len(state.accounts) == 1
  assert state.accounts[0].account_id == account_id
  assert state.accounts[0].evidence.profile_present
  assert state.accounts[0].evidence.raw_present
  assert state.accounts[0].evidence.merged_present
  ```

- [x] **Step 2: Add a dashboard view-model regression test.**

  Pass the `PlatformState` from the fixture to `_account_rows`. Assert exactly one row and its combined presentation fields:

  ```python
  rows = _account_rows([state])
  assert len(rows) == 1
  assert rows[0]["Account ID"] == account_id
  assert rows[0]["Lifecycle"] == "Active"
  assert rows[0]["Profile"] == "Present"
  assert rows[0]["Raw"] == "Present"
  assert rows[0]["Merged"] == "Present"
  ```

  Also extract/test the action-target filter: only states with a non-null canonical `account_id` and catalog lifecycle are selectable. Unclassified local evidence remains in the inventory table and metrics but cannot invoke lifecycle, binding, auth, or sync actions against a nonexistent catalog record.

- [x] **Step 3: Run the application and dashboard regression tests.**

  Run:

  ```bash
  .venv/bin/pytest -q \
    tests/application/test_platforms.py::test_platform_state_exposes_one_v2_account_for_catalog_binding_and_uuid_data \
    tests/test_dashboard_accounts.py::test_account_rows_emit_one_row_per_canonical_uuid \
    tests/test_dashboard_accounts.py::test_unclassified_evidence_is_visible_but_not_an_action_target
  ```

  Expected: PASS. The dashboard receives an already-consolidated inventory; no view-layer `drop_duplicates()` is added.

### Task 4: Verify the focused contract and review the local UI safely

**Files:**
- Modify: none expected
- Test: `tests/test_accounts.py`
- Test: `tests/application/test_accounts.py`
- Test: `tests/application/test_platforms.py`
- Test: `tests/test_dashboard_accounts.py`

**Interfaces:**
- Verifies: the read-only inventory, runnable-account behavior, action lifecycle gates, application state, and Accounts presentation agree on a single UUID identity.
- Excludes: parser/unify regeneration, real account modification, DVC writes, and publication.

- [x] **Step 1: Run the focused suite.**

  Run:

  ```bash
  .venv/bin/pytest -q \
    tests/test_accounts.py \
    tests/application/test_accounts.py \
    tests/application/test_platforms.py \
    tests/test_dashboard_accounts.py
  ```

  Expected: PASS with no test changed solely to preserve a duplicate state.

- [x] **Step 2: Perform a non-mutating Accounts UI smoke test.**

  If a Streamlit server is running, use Streamlit `AppTest` or the dashboard's existing test harness to select the Accounts page without clicking preview/apply/sync/auth controls. Confirm that the data frame has one row per unique non-empty `Account ID`, the lifecycle counts reflect catalog records rather than duplicate evidence rows, and each action selector lists a UUID once.

  If no browser surface is available, the Task 3 view-model test is the required automated equivalent; record that visual inspection was unavailable rather than using a headless browser that mutates local state.

- [x] **Step 3: Run the final static checks and inspect scope.**

  Run:

  ```bash
  git diff --check
  git status --short
  ```

  Expected: only source and test files for this fix are changed. Stop before staging, committing, DVC publication, or Git publication.

- [x] **Step 4: Run the full test suite before declaring the implementation complete.**

  Run `.venv/bin/pytest -q`. This is the repository merge gate; it must pass without regenerating data.

## Coverage Review

- UUID-only identity: Task 2 emits catalog v2 states by `account_id` and forbids v2 catalog lookup by profile or technical locator.
- Lossless evidence: Tasks 1 and 2 cover combined bound evidence and unmatched unclassified evidence without inference.
- Dashboard duplication and action-target impact: Task 3 verifies the application boundary and displayed rows; Task 4 verifies the selector/count contract through the safest available UI harness.
- Compatibility and preservation: Task 2 retains the existing v1 branch and catalog-only/historical records; no task alters durable data.
- Validation/publication bounds: Task 4 stops after focused tests, static checks, and a read-only smoke test.
