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

# Install the package in editable mode + dev dependencies
pip install -e ".[dev]"

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

**CLIs (Claude Code, Codex, Gemini CLI):** no login needed. Data
is copied directly from the local directory
(`~/.claude/projects/`, `~/.codex/sessions/`, `~/.gemini/tmp/`).

## First capture

Recommended starting with 1 platform to validate:

```bash
python scripts/chatgpt-sync.py
```

Sync runs everything in sequence:

1. **Capture** — downloads via the internal API, saves to `data/raw/ChatGPT/`.
2. **Asset download** — images (DALL-E, uploads), project files,
   etc.
3. **Reconcile** — consolidates with the previous capture in
   `data/merged/ChatGPT/`. Conversations that disappeared from the server
   end up with `is_preserved_missing=True`.
4. **Parse** (manual, does not run automatically) — converts to parquet:

```bash
python scripts/chatgpt-parse.py
```

This generates 4-6 parquets in `data/processed/ChatGPT/` in the canonical schema.

Repeat sync for other platforms. Then consolidate everything into a
single cross-platform set:

```bash
python scripts/unify-parquets.py
```

This generates 11 parquets in `data/unified/`.

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

## Optional: DVC backup (full vault)

The pipeline writes to `data/raw/`, `data/merged/`, `data/processed/`,
`data/unified/`, `data/external/`. These directories are gitignored — they
hold personal data that must not go to the repo.

If you want a versioned backup (so you can delete locally and recover
later, or roll back to any historical state), set up DVC with your own
Google Drive folder:

```bash
# 1. Install dvc[gdrive] (already in requirements.txt)
.venv/bin/pip install -r requirements.txt

# 2. Create a folder in your own Google Drive, copy its ID from the URL.
#    Then point DVC at it (overrides the default config from this repo):
.venv/bin/dvc remote modify --local gdrive_remote url gdrive://<YOUR_FOLDER_ID>

# 3. Optional — set your own OAuth client (avoids sharing the default app):
#    https://console.cloud.google.com/auth/clients (create a Desktop client)
.venv/bin/dvc remote modify --local gdrive_remote gdrive_client_id <YOUR_CLIENT_ID>
.venv/bin/dvc remote modify --local gdrive_remote gdrive_client_secret <YOUR_CLIENT_SECRET>

# 4. Track and push (~minutes to hours depending on data volume)
.venv/bin/dvc add data/raw data/merged data/processed data/unified \
    data/external/manual-saves data/external/deep-research-md \
    data/external/perplexity-orphan-threads data/external/deepseek-snapshots \
    data/external/chatgpt-extension-snapshot data/external/claude-ai-snapshots \
    data/external/notebooklm-snapshots data/external/openai-gdpr-export
git add data/*.dvc data/external/*.dvc data/.gitignore data/external/.gitignore
git commit -m "data: initial dvc snapshot"
.venv/bin/dvc push
```

The `--local` flag writes to `.dvc/config.local` (gitignored), so your
`gdrive_folder_id` and OAuth secret never go to a public fork. The repo's
default `.dvc/config` is kept as a working example; you only need to
override what's specific to you.

To restore on a new machine: clone the repo, restore `.dvc/config.local`
(from your backup or recreate via the same `dvc remote modify --local`
commands), then `dvc pull`.

Full operational guide: [dvc-runbook.md](dvc-runbook.md).

## Next steps

- **Local dashboard** — `PYTHONPATH=. streamlit run dashboard.py`
- **Per-platform descriptive documents** —
  `quarto render notebooks/<plat>.qmd` (see [operations.md](operations.md))
- **Parquet analysis** — read `data/unified/*.parquet` in pandas/DuckDB
- **Known limitations** — [LIMITATIONS.md](LIMITATIONS.md)
