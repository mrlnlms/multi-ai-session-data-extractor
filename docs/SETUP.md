# Detailed setup

Complete guide from zero to get the project running and the first capture
working. For a project overview, see [README.md](../README.md).

## Prerequisites

- **Python ≥3.12** (tested on 3.12 and 3.14)
- **macOS or Linux** (Windows not tested)
- **~5GB of free space** (depends on how many conversations you have)
- **Git** to clone the repository

Check the version:

```bash
python3 --version
# Python 3.12.0 or higher
```

## Installation

```bash
git clone <repo-url>
cd multi-ai-session-data-extractor

# Create isolated virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the complete project environment
pip install -r requirements.txt

# Install the Chromium browser for Playwright (~200MB)
playwright install chromium
```

From here on, whenever you open a new terminal:

```bash
source .venv/bin/activate
```

## Login (once per platform)

Each platform needs an interactive login once. The script opens a
browser, you log in manually, and the profile is saved at
`.storage/<platform>-profile-<account>/` (gitignored).

```bash
python scripts/chatgpt-login.py
python scripts/claude-login.py
python scripts/deepseek-login.py
python scripts/gemini-login.py
python scripts/notebooklm-login.py
python scripts/perplexity-login.py
python scripts/qwen-login.py
```

**What to expect:**

1. A Chromium window opens on the platform's login page.
2. You complete the login (email, password, possibly captcha or 2FA).
3. When the platform's dashboard/home loads, the script detects it and
   closes the browser on its own — or you can close it manually.
4. The profile is preserved and subsequent syncs do not ask for login
   again (until the cookie expires — usually months).

**CLIs (Claude Code, Codex, Gemini CLI, Antigravity CLI):** no login needed for
the collector. Data
is copied directly from the local directory
(`~/.claude/projects/`, `~/.codex/sessions/`, `~/.gemini/tmp/`).

## First capture

Recommended starting with 1 platform to validate:

```bash
python scripts/chatgpt-sync.py
```

The standalone web sync runs capture, asset download, and reconcile:

1. **Capture** — downloads via the internal API, saves to `data/raw/ChatGPT/`.
2. **Asset download** — images (DALL-E, uploads), project files,
   etc.
3. **Reconcile** — consolidates with the previous capture in
   `data/merged/ChatGPT/`. Conversations that disappeared from the server
   end up with `is_preserved_missing=True`.
When running a web sync script directly, run its parser afterward to convert
the reconciled data to parquet:

```bash
python scripts/chatgpt-parse.py
```

This generates 4-6 parquets in `data/processed/ChatGPT/` in the canonical schema.

The dashboard and headless pipeline perform this parser step automatically
after each successful web sync and before unification. CLI sync scripts already
include their parser step.

Repeat sync for other platforms. Then consolidate everything into a
single cross-platform set:

```bash
python scripts/unify-parquets.py
```

This generates 13 parquets in `data/unified/`.

## Multi-account (Gemini, NotebookLM)

Gemini supports 2 Google accounts. NotebookLM supports 3 (including legacy).

For Gemini:

```bash
# Login to each account separately
python scripts/gemini-login.py --account 1
python scripts/gemini-login.py --account 2

# Sync both accounts
python scripts/gemini-sync.py

# Or just one
python scripts/gemini-sync.py --account 1
```

Same pattern for NotebookLM (`--account 1` / `--account 2`).

## Common troubleshooting

### "Expired cookie" / "redirect to login" during sync

The platform's cookie expired. Redo the login:

```bash
python scripts/chatgpt-login.py
```

### ChatGPT opens a window even during sync (not headless)

Expected behavior — Cloudflare detects clients without a window. Same
for Perplexity. Other platforms (Claude.ai, Gemini, NotebookLM,
Qwen, DeepSeek) run without a visible window.

### "Discovery drop detected" / sync aborted

The extractor protects against partial captures. If the initial listing
dropped more than 20% compared to the largest historical capture, it aborts
before writing so as not to corrupt the cumulative `data/raw/`.

Common causes:

- Unstable discovery endpoint (e.g. OpenAI's `/projects` occasionally
  returns 404)
- Cookie expired and fallback only partially resolves
- Server changed structure

Solutions:

```bash
# Try again (transient instability usually resolves)
python scripts/chatgpt-sync.py

# Investigate manually
python scripts/chatgpt-sync.py --dry-run
```

### Sync takes too long

The first capture is slow because it downloads **everything**. Subsequent
captures are incremental and fast (seconds to minutes).

Typical first-capture times:

| Platform | Time |
|---|---|
| Claude.ai | 10-30 min |
| ChatGPT | 5-30 min (depends on volume) |
| NotebookLM | 30-90 min (large binaries — slide decks, audios) |
| Others | 1-10 min |

### "ModuleNotFoundError" when running scripts

You forgot to activate `.venv` or you're not in the project root
directory:

```bash
source .venv/bin/activate
cd /path/to/multi-ai-session-data-extractor
PYTHONPATH=. python scripts/<script>.py
```

### Perplexity HTTP 403 during sync

Same cause as ChatGPT — Cloudflare. Sync already runs with a visible
window for this platform; if you still get 403, recreate the profile:

```bash
rm -rf .storage/perplexity-profile-default
python scripts/perplexity-login.py
```

### I want to recapture from scratch (discard incremental)

```bash
python scripts/chatgpt-sync.py --full
```

This forces refetch of all conversations (not just the ones that changed). It still
preserves whatever is in `data/raw/`.

### I want to delete everything and start over

```bash
# CAUTION: deletes raw + merged + processed (but .storage/ remains)
rm -rf data/raw data/merged data/processed data/unified
```

Cookies/profile (`.storage/`) are not deleted. To delete everything
including logins:

```bash
rm -rf data/ .storage/
```

## DVC: recoverable vault for the current data

The pipeline writes to `data/raw/`, `data/merged/`, `data/processed/`,
`data/unified/`, `data/external/`. These directories are gitignored — they
hold personal data that must not go to the repo.

This repository uses DVC as a recoverable vault for the **current canonical
base**. Git versions the code and the small `.dvc` pointers; the remote stores
the large personal data. It is not a promise that every historical data
snapshot in Git can be restored forever: old DVC objects may be deliberately
discarded after the current state has been published and verified.

### Restore an existing archive on a new machine

Restore your private `.dvc/config.local` first (it contains the local OAuth
configuration and is intentionally outside Git), then pull the current data:

```bash
# DVC is already included in requirements.txt
.venv/bin/pip install -r requirements.txt
.venv/bin/dvc pull
```

The first pull may open an OAuth flow. Browser profiles in `.storage/` are not
part of this vault; log in to platforms again before collecting.

### Publish a new, validated collection

After sync, parse, and unify have completed successfully, update the tracked
data pointers and publish the current base. This is a deliberate operation:
`dvc push` writes to external storage and `git push` publishes the new
pointers. Use the exact command set and validation sequence in the runbook;
do not use the legacy `scripts/backup_to_dvc.sh`.

Full operational guide, including storage cleanup: [dvc-runbook.md](dvc-runbook.md).

## Next steps

- **Local dashboard** — `PYTHONPATH=. streamlit run dashboard.py`
- **Per-platform descriptive documents** —
  `quarto render notebooks/<plat>.qmd` (see [operations.md](operations.md))
- **Parquet analysis** — read `data/unified/*.parquet` in pandas/DuckDB
- **Known limitations** — [LIMITATIONS.md](LIMITATIONS.md)
