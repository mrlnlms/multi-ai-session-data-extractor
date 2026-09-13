# Dashboard Entrypoint Cleanup Implementation Plan

> **For agentic workers:** Execute these steps inline and verify each boundary before continuing.

**Goal:** Remove environment-generated skill links, colocate the Streamlit entrypoint with its dashboard package, and prevent legacy root/script references from returning.

**Architecture:** `dashboard/app.py` is the thin Streamlit UI entrypoint and imports reusable dashboard modules plus the official report-server workflow in `src`. `.runtime/` remains the ignored home for disposable operational state; `.agents/` and `.claude/` are not project structure.

**Tech Stack:** Python, Streamlit, pytest, Git

**Spec:** User request in the 2026-09-13 cleanup session and canonical `AGENTS.md`.

## Global Constraints

- Do not alter `data/` or `.storage/`.
- Do not run `dvc push`.
- Do not commit or push without a new explicit request.
- Keep dashboard code as a Streamlit layer and reusable workflow implementation in `src/`.

---

### Task 1: Remove generated skill links

**Files:**
- Remove locally: `.agents/skills/developing-with-streamlit`
- Remove locally: `.claude/skills/developing-with-streamlit`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Streamlit's installed skill copies from `.venv`.
- Produces: no repository-local agent skill directories.

- [x] Verify both directories contain only the ignored Streamlit symlink.
- [x] Remove `.agents/` and `.claude/` locally.
- [x] Replace narrow ignore entries with directory-level ignores so installer recreation stays invisible.

### Task 2: Colocate the Streamlit entrypoint

**Files:**
- Move: `dashboard.py` to `dashboard/app.py`
- Modify: `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/SETUP.md`, `docs/operations/dashboard.md`

**Interfaces:**
- Consumes: `dashboard.*` UI modules and `src.workflows.serve_reports`.
- Produces: `PYTHONPATH=. .venv/bin/streamlit run dashboard/app.py`.

- [x] Move the entrypoint into the dashboard package.
- [x] Replace removed shell-script subprocesses with `is_running()`, `start_server()`, and `stop_server()`.
- [x] Update every maintained launch command.

### Task 3: Add regression coverage and validate

**Files:**
- Modify: `tests/test_architecture_layout.py`

**Interfaces:**
- Consumes: final repository layout.
- Produces: architectural assertions for the dashboard entrypoint and generated skill directories.

- [x] Add assertions that `dashboard/app.py` exists and root `dashboard.py` does not.
- [x] Assert maintained Python contains no references to removed scripts.
- [x] Run old-reference searches, focused tests, the full suite, `git diff --check`, and final diff review.
