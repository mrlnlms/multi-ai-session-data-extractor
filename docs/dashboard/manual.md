# Dashboard — feature manual + operations

Living document of what exists in the dashboard (feature manual +
operations). Paired with `plan.md` (historical plan of the 4 phases).

Run with:

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py
```

Opens at <http://localhost:8501>. Operations details (background,
healthcheck, programmatic access via `AppTest`, MCP browser, gotchas) in
section 10 of this file.

---

## 1. Philosophy ("zero interpretation")

The dashboard presents data, **does not interpret it**. Counts, distributions,
timelines, status. No sentiment analysis, semantic clustering, qualitative
coding, "quality" ranking, or narrative discovery. Whoever wants heavy
interpretation takes the parquets to their own analytical pipeline.

Also **read-only**: the dashboard never edits the data the sync produced.
Buttons trigger the original sync via subprocess; they don't rewrite JSONs or
re-merge on their own.

---

## 2. General layout

### Sidebar (always visible)

| Element | What it does |
|---|---|
| Title "AI Sessions Tracker" | Branding, no action |
| "🏠 Overview" button | Returns to the home page (same as "← Back" in drill-down) |
| Quarto status | Shows `✅ installed` or `➖ missing`. When installed, the drill-down for each platform shows a "View detailed data" link to `notebooks/_output/<plat>.html`. |
| Caption about logs | Reminds where `capture_log.jsonl` and `reconcile_log.jsonl` live |
| "🔁 Reload data" button | Clears `st.cache_data` and re-runs the script. Use after running sync in the terminal so the dashboard reflects the changes without restart |

### Routing

Single-page, decided by `st.session_state["view"]`:

- `"overview"` (default) → renders `dashboard/pages/overview.py`
- `"platform"` + `selected_platform` → renders `dashboard/pages/platform.py`

Switching views does not destroy button state; session_state persists while
the browser tab stays open.

---

## 3. Overview page

### Cross-platform KPIs (4 metrics at the top)

| Metric | Source |
|---|---|
| **Total captured** | Sum of `total_convs` from all mergeds found |
| **Active** | Sum of `active` (seen on the server today) |
| **Preserved missing** | Sum of `preserved_missing` (cumulative, in merged but gone from the server) |
| **Platforms with data** | How many of the 7 known have any capture |

### "Last global sync" line

Picks the most recent capture across platforms and shows `<relative> (<plat>, <UTC date>)`.
Disappears if no platform has captures.

### Alerts

- ⚠️ `N platforms behind` — lists those in red status (>3d without sync)
- 🚨 `Discovery drop detected on: ...` — flags when the most recent discovery
  dropped more than 20% vs the highest historical value (symptom of `/projects` flaky on ChatGPT)

### "🔄 Update all" button

Sequential: for each platform with a sync or export script available, fires
a blocking `subprocess.run(...)`, shows a spinner with the name, displays ✅ or ❌ at the
end. Clears the cache at the end so the UI reflects the new data.

**Important:** ChatGPT runs in headed mode by design (Cloudflare detects
headless). Playwright will open a browser during sync — expected
behavior, not a bug. Documented in `CLAUDE.md` in the "Headless vs headed
per platform" section.

### Platforms table

One row per known platform (including those that haven't run yet):

| Column | Content |
|---|---|
| Status | Badge: 🟢 (<24h) · 🟡 (1-3d) · 🔴 (>3d) · ⚫ (never ran) |
| Platform | Canonical name (ChatGPT, Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity) |
| Last capture | Relative time of the last entry in `capture_log.jsonl` |
| Last conv touched (server) | Placeholder `—` in Phase 1 (requires opening merged.json — calculation only done in drill-down) |
| Total / Active / Preserved | Numbers from merged if it exists, `—` otherwise |

### Navigation buttons

Below the table, 1 button per platform — clicking changes `view` to `platform`
and sets `selected_platform`. Equivalent to a direct drill-down.

### Capture timeline

Plotly with `discovery_total` over `run_started_at`, one line per
platform with captures. Empty shows a guidance message.

---

## 4. Drill-down page (one platform)

### Header

- "← Back" button at the top (returns to overview)
- Title `<badge> <Name>` + status caption

### Status panel (3 metrics)

| Metric | Content |
|---|---|
| **Last capture** | Relative time + caption with absolute UTC date |
| **Last reconcile** | Relative time + caption with absolute UTC date |
| **Local storage** | Sum of `data/raw/<plat>/` + `data/merged/<plat>/`, with breakdown in the caption |

Above it: red 🚨 alert if there is a discovery drop in the logs.

### Sync button

For each platform:

- If `<plat>-sync.py` exists (all 7 platforms today): label `🔄 Sync <Name>`, runs
  `chatgpt-sync.py --no-voice-pass` (or equivalent)
- If only `<plat>-export.py` exists (Claude.ai, Gemini, NotebookLM, Qwen,
  DeepSeek, Perplexity): label `🔄 Export <Name> (no orchestrator yet)`,
  runs the standalone export
- Neither exists: caption explaining the script is missing

Behavior on execution:

1. `st.spinner` with the final command visible (e.g., "Running chatgpt-sync.py --no-voice-pass...")
2. Blocking (subprocess.run with capture_output)
3. Success (`returncode == 0`): `✅ Sync complete` + "stdout" expander with the
   last 3000 chars + cache clear + rerun to reflect the data
4. Failure (`returncode != 0`): `❌ Failed (exit N)` + "stderr" expander with
   everything that came in
5. Exception: `❌ <message>` directly

### Captured content (only if merged.json exists)

Reads cached `<plat>_merged.json` (key = path + mtime).

Metrics in 3 rows of cards:

1. Total convs · Active · Preserved missing · Archived
2. In projects · Standalone · Distinct projects
3. Oldest conv · Most recent activity

And a standalone metric: Estimated messages (count of nodes with non-null
`message` in the cumulative `mapping`).

### Creation-by-month chart

Plotly bar chart with the count of convs created per month (key `YYYY-MM`).
Useful for seeing the adoption curve over time.

### Expanders

Three detailed lists, all hidden by default to avoid clutter:

- **Models used (top 10)** — extracts `metadata.model_slug` or
  `metadata.default_model_slug` from each message in the mapping. Doesn't have a 1:1 with
  conv count (one conv can use multiple models)
- **Top projects by convs** — aggregates by `_project_id`, shows name when
  known (`_project_name`)
- **Preserved convs (deleted on server)** — lists all convs whose
  `_last_seen_in_server` doesn't match the current date

### Project sources (only if there's a folder in raw)

Block with 4+3 metrics about `data/raw/<plat>/project_sources/`:

- Projects · With files · Empty · Total size
- Active files · Preserved files · 100% preserved projects

Detects `_preserved_missing: true` in `_files.json` entries to count
preservation.

### History (tabs)

Tabs "Captures" and "Reconciles" with tables built from the `.jsonl` files:

| Captures | Reconciles |
|---|---|
| Start · Duration · Discovery · Fetch ok · Errors | When · Added · Updated · Copied · Preserved missing · Warnings |

Newest at the top.

---

## 5. Caches and invalidation

To avoid re-reading 119MB of `chatgpt_merged.json` on every interaction:

```python
@st.cache_data(show_spinner=False)
def _cached_merged_stats(merged_path_str: str, mtime: float):
    return compute_merged_stats(Path(merged_path_str))
```

The cache key includes the file's `mtime`: if sync rewrites merged,
the mtime changes and the cache invalidates automatically.

Manually:

- "🔁 Reload data" button in the sidebar
- After every sync started by the dashboard (automatic cache.clear)

---

## 6. Automatic platform discovery

`dashboard/data.py` declares:

```python
KNOWN_PLATFORMS = ["ChatGPT", "Claude.ai", "Gemini", "NotebookLM",
                   "Qwen", "DeepSeek", "Perplexity"]
```

But it also scans `data/raw/` and `data/merged/`. The final list is
`KNOWN_PLATFORMS + extras found on disk`. Result:

- Known platforms appear even without a capture (status ⚫)
- A new folder on disk shows up automatically, no code change needed

---

## 7. Errors and friendly messages

| Situation | What it shows |
|---|---|
| Platform with no capture | `No capture found for <plat>. Use the button below to run the first sync.` |
| Platform with no script | `No sync or export script for <plat> yet. Implementing scripts/<plat>-sync.py unlocks the button.` |
| Sync failed | Exit code + stderr expander |
| Subprocess exception | Exception message directly |
| Discovery drop | Red banner explaining the 20% threshold |
| No merged.json | Caption "No merged.json found for this platform." |
| Quarto missing | In sidebar: `➖ missing`. Drill-down does not show "View detailed data" link — install `quarto` (brew/standalone) and re-run `<plat>-parse.py` + `quarto render notebooks/<plat>.qmd`. |

---

## 8. What does **not** yet exist

V3 parsers, descriptive Quarto, and sync orchestrator for the 7 platforms are
shipped. What remains out of scope for the dashboard (by design):

- **Models per conv**: today we count `model_slug` per message (fine
  granularity). "Default model of the conv" is derived from the canonical parser
  (`Conversation.model` = last assistant `model_slug`), but the dashboard
  still presents the per-message granularity.
- **Entire deleted projects** (cross-source): drill-down already shows
  "100% preserved projects" in project_sources, but has no cross
  visualization of orphaned chats from deleted projects.
- **Aggregated cross-platform view**: overview has cross KPIs but no
  side-by-side comparison (e.g., temporal distribution of all 7 simultaneously).
  Belongs in `notebooks/00-overview.qmd` (backlog).
- **Interpretive analysis** — sentiment, clustering, topic detection. By
  design this lives in external pipelines (this project only produces parquets).

---

## 9. Relevant files

```
dashboard.py                       # entry point
dashboard/
├── __init__.py
├── data.py                        # discovery + reading logs/JSON
├── metrics.py                     # metric extraction (catalog sec 6 of the plan)
├── components.py                  # status badge, time/size formatting
├── sync.py                        # subprocess wrapper, script detection
└── pages/
    ├── overview.py
    └── platform.py
```

`README.md` — "Dashboard" section with installation and basic commands.

---

## 10. Operations

### 10.1. Bring up

Prerequisite: venv with `requirements.txt` deps installed.

Default command (foreground, holds the terminal):

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py
```

Runs at <http://localhost:8501> by default. `Ctrl+C` in the terminal to stop.

In the background (frees the shell, log to a file):

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py \
  --server.headless true \
  --browser.gatherUsageStats false \
  > /tmp/dashboard.log 2>&1 &
```

Different port (if 8501 is occupied):

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py --server.port 8512
```

### 10.2. Healthcheck

```bash
curl -sf http://localhost:8501/_stcore/health && echo OK
```

List process:

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN
```

### 10.3. Stop

Foreground: `Ctrl+C`. Background:

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN | awk 'NR>1 {print $2}' | xargs kill
```

### 10.4. Access

| Who | URL |
|---|---|
| You, browser on this machine | <http://localhost:8501> |
| Another device on the same LAN | `http://<machine-ip-on-the-lan>:8501` (Streamlit prints it on boot as "Network URL") |
| Another Claude session with MCP browser | <http://localhost:8501> via `mcp__claude-in-chrome__tabs_create_mcp` |
| Another Claude session without browser | API `streamlit.testing.v1.AppTest` (programmatic) |

**Do not use the "External URL"** that Streamlit prints on boot — it's your
public IP, exposing the dashboard to the internet without any authentication.
Auth is explicitly out of scope (see `dashboard-plan.md` section 9).

### 10.5. Programmatic access (no browser)

Another Claude session can run the app without bringing up a server, to read state
or run a smoke test:

```python
from streamlit.testing.v1 import AppTest

# overview
at = AppTest.from_file('dashboard.py').run(timeout=30)
print('title:', at.title[0].value)
print('errors:', [str(e) for e in at.error])
print('metrics:', [(m.label, m.value) for m in at.metric])

# drill-down for a platform
at = AppTest.from_file('dashboard.py')
at.session_state['view'] = 'platform'
at.session_state['selected_platform'] = 'ChatGPT'
at.run(timeout=30)
print('metrics:', [(m.label, m.value) for m in at.metric])
print('dataframes:', len(at.dataframe))
```

Useful for: smoke test, another session checking state without a browser, future CI.

The `missing ScriptRunContext` warning is harmless (expected outside the Streamlit runtime).

### 10.6. Access via Claude-in-Chrome (another session)

If the other session has the MCP browser:

1. Make sure Streamlit is up (10.1 or healthcheck 10.2)
2. `mcp__claude-in-chrome__tabs_create_mcp(url="http://localhost:8501")`
3. Wait for it to render (Streamlit uses WebSocket — about 2-3s for the UI to mount)
4. `mcp__claude-in-chrome__read_page` to extract text
5. `mcp__claude-in-chrome__computer` to click buttons

Target elements with `data-testid="stMetricLabel"`,
`data-testid="stDataFrame"`, etc. — Streamlit generates stable IDs.

### 10.7. Common gotchas

| Symptom | Cause / Fix |
|---|---|
| `ModuleNotFoundError: dashboard` | Missing `PYTHONPATH=.` before `streamlit run` |
| Port 8501 occupied | `--server.port <other>` or kill the process (10.3) |
| Changed data outside the dashboard, UI doesn't update | Click "🔁 Reload data" in the sidebar |
| Sync hangs with Playwright browser open | Expected for ChatGPT (Cloudflare detects headless). Wait for the subprocess to finish — UI shows a spinner |
| Platforms table doesn't show some entry | Automatic discovery scans `data/raw/<plat>/` and `data/merged/<plat>/`. If empty, it stays `⚫ never ran`. If not even that, check the name in `KNOWN_PLATFORMS` (`dashboard/data.py`) |
