# Operations — common terminal commands

To run the pipeline for the 7 platforms on your own, without depending on me.
ChatGPT serves as the living reference — the others follow the same pattern
with small per-platform adaptations.

---

## Prerequisite: activate venv

In any command below, either:
- Use the venv python directly: `.venv/bin/python` (most explicit way)
- Or activate the venv in the session: `source .venv/bin/activate` (then just `python`)

The examples below use `.venv/bin/python` for clarity.

---

## Sync per platform

Each platform has its own orchestrator (`<plat>-sync.py`). Capture +
reconcile + (assets, when applicable) in one run. Incremental by default.

### ChatGPT

```bash
PYTHONPATH=. .venv/bin/python scripts/chatgpt-sync.py --no-voice-pass
```

### Claude.ai

```bash
PYTHONPATH=. .venv/bin/python scripts/claude-sync.py
# If sync left gaps due to transient timeout:
PYTHONPATH=. .venv/bin/python scripts/claude-refetch-known.py
```

### Perplexity

```bash
PYTHONPATH=. .venv/bin/python scripts/perplexity-sync.py
```

### Qwen

```bash
PYTHONPATH=. .venv/bin/python scripts/qwen-sync.py
```

### DeepSeek

```bash
PYTHONPATH=. .venv/bin/python scripts/deepseek-sync.py
```

### Gemini (multi-account)

```bash
# Default: runs both accounts (account-1 + account-2) in sequence
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py

# Or just one account
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py --account 1
```

### NotebookLM

Multi-account (3 accounts: account-1 en, account-2 pt-BR, account-3 legacy more.design):

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py             # both web accounts
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py --account 1 # only account-1
```

---

## ChatGPT details (reference)

ChatGPT has more flags because it's the most mature platform. Others follow
a subset of these.

**Useful flags:**

| Flag | What it does |
|---|---|
| `--no-voice-pass` | Skip audio message scan (faster) |
| `--dry-run` | Discovery only, doesn't download or reconcile. Good for seeing how many convs the server shows |
| `--full` | Refetch all convs (brute force, slow) |
| `--no-binaries` | Skip asset and project source download |
| `--no-reconcile` | Skip the final reconcile step |
| `-v` | Verbose (DEBUG logs) |

**What to expect from a normal (incremental) run:**
- Browser opens (ChatGPT requires headed mode due to Cloudflare)
- Discovery finds N convs (e.g., 1168)
- Fetch downloads only the delta (e.g., 1 new conv)
- Hardlink stage NO LONGER happens (single folder, no need)
- Asset download skips everything that already exists
- Reconcile generates a new `chatgpt_merged.json`

---

## Individual stages (when you want to run just one part)

```bash
# 1. Login (1x per account, opens browser)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-login.py

# 2. Capture only (no assets/sources/reconcile)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-export.py

# 3. Asset download
PYTHONPATH=. .venv/bin/python scripts/chatgpt-download-assets.py data/raw/ChatGPT

# 4. Project sources download
PYTHONPATH=. .venv/bin/python scripts/chatgpt-download-project-sources.py data/raw/ChatGPT

# 5. Reconcile (raw → merged)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-reconcile.py data/raw/ChatGPT
```

---

## See status without running anything

```bash
# Last capture — when + counts
cat data/raw/ChatGPT/LAST_CAPTURE.md

# Last reconcile — total convs, preserved, etc.
cat data/merged/ChatGPT/LAST_RECONCILE.md

# Cumulative capture history (1 line per run)
cat data/raw/ChatGPT/capture_log.jsonl

# Cumulative reconcile history
cat data/merged/ChatGPT/reconcile_log.jsonl

# Total convs in merged (Python one-liner)
.venv/bin/python -c "import json; d=json.load(open('data/merged/ChatGPT/chatgpt_merged.json')); print(f'{len(d[\"conversations\"])} convs')"
```

---

## Tests

```bash
# Run the full suite
PYTHONPATH=. .venv/bin/pytest tests/ -v

# Only ChatGPT tests
PYTHONPATH=. .venv/bin/pytest tests/extractors/chatgpt/ tests/reconcilers/test_chatgpt.py tests/test_chatgpt_sync.py -v

# Exclude parsers (which fail when pyarrow is missing — non-blocking)
PYTHONPATH=. .venv/bin/pytest tests/ --ignore=tests/parsers
```

---

## Merged rollback (worst case)

If a reconcile produces wrong output and you want to roll back:

```bash
# 1. Always automatic backup — before any manual reconcile:
cp data/merged/ChatGPT/chatgpt_merged.json /tmp/merged-backup-$(date +%Y%m%d-%H%M).json

# 2. If something goes wrong, restore:
cp /tmp/merged-backup-YYYYMMDD-HHMM.json data/merged/ChatGPT/chatgpt_merged.json
```

---

## Setup from scratch (on another machine or if you deleted `.venv/`)

```bash
cd /path/to/project
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# Login (1x per account, per platform)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-login.py
PYTHONPATH=. .venv/bin/python scripts/claude-login.py
PYTHONPATH=. .venv/bin/python scripts/perplexity-login.py
PYTHONPATH=. .venv/bin/python scripts/qwen-login.py
PYTHONPATH=. .venv/bin/python scripts/deepseek-login.py
PYTHONPATH=. .venv/bin/python scripts/gemini-login.py --account 1
PYTHONPATH=. .venv/bin/python scripts/gemini-login.py --account 2

# First capture per platform (full, slow)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-sync.py --no-voice-pass
PYTHONPATH=. .venv/bin/python scripts/claude-sync.py
# ... same for the others
```

## Render descriptive Quarto (self-contained HTML)

After `<plat>-parse.py` (or `<cli>-copy.py` + `<cli>-parse.py`), generate
descriptive HTML. The 14 qmds share `notebooks/_template.qmd` — adding a new
section means changing 1 place only.

```bash
# Web platforms (7)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/claude-ai.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/perplexity.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/qwen.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/deepseek.qmd

# CLIs (3) — local data, no web capture
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/claude-code.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/codex.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/gemini-cli.qmd

# Gemini multi-account (consolidated + 2 per-account)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/gemini.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/gemini-acc-1.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/gemini-acc-2.qmd

# NotebookLM multi-account (consolidated + 2 per-account + 1 legacy)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm-acc-1.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm-acc-2.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm-legacy.qmd
```

Output in `notebooks/_output/<plat>.html` (gitignored, ~40MB self-contained,
~20-60s each).

**Cross-platform overviews** (from `data/unified/`):

```bash
# Materialize unified first (after any <plat>-parse.py)
PYTHONPATH=. .venv/bin/python scripts/unify-parquets.py

# Render the 4 overviews
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview.qmd      # all 10 sources
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-web.qmd  # 6 web
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-cli.qmd  # 3 CLIs
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-rag.qmd  # NotebookLM
```

**Serve locally:**

```bash
./scripts/serve-qmds.sh           # bring up (default = start)
./scripts/serve-qmds.sh status    # running or stopped?
./scripts/serve-qmds.sh open      # opens 15 tabs in the browser
./scripts/serve-qmds.sh stop      # stop
./scripts/serve-qmds.sh restart   # stop + start

# Variables (optional):
PORT=8766 ./scripts/serve-qmds.sh         # different port
OUTPUT_DIR=other ./scripts/serve-qmds.sh  # other dir
```

PID + log written to `.serve-qmds.{pid,log}` (gitignored). Server runs in
the background — close the terminal and it keeps running until `stop`.

**Helpers and tests:** `src/parsers/quarto_helpers.py` covers setup
(setup_views_with_manual + setup_notebook), schema/query (has_col/has_view/
table_count) and display (fmt_pct/fmt_int/safe_int/show_df/plotly_bar). Tests
in `tests/parsers/test_quarto_helpers.py` (40 tests).

---

## Dashboard pipeline — recovery quando algo quebra

O dashboard Streamlit (`streamlit run dashboard.py`) roda o pipeline 4-stage:
**Sync → Unify → Quarto → Publish (DVC + git)**. Gating aborta o que vem
depois quando algo crítico falha — nada de commitar estado quebrado.

### Comportamento de falha por stage

| Stage falhou | O que o pipeline faz | O que você faz |
|---|---|---|
| **1 Sync** parcial (1+ plats) | Stages 2-4 rodam só com plats OK | Abrir página da plat afetada, "Run full pipeline (this platform)" |
| **1 Sync** total (TODAS) | Aborta — stages 2-4 marcadas `aborted` | Verificar cookies/rede; possivelmente `<plat>-login.py` |
| **2 Unify** | Stages 3-4 `aborted` | `PYTHONPATH=. .venv/bin/python scripts/unify-parquets.py` standalone pra ver erro |
| **3 Quarto** | Stage 4 `aborted` (não publica estado quebrado) | `quarto render notebooks/<plat>.qmd` pra ver erro do qmd |
| **4 Publish** | Para no sub-step que falhou | Idempotente — re-clicar "Update all" retoma. `dvc push` e `git push` são no-op se nada novo |

### Lockfile stale (`Pipeline already running`)

Se o Streamlit crashou no meio de uma rodada, o `.update-all.lock` fica.
Acquire da próxima rodada **já detecta PID morto automaticamente** e
mata processos filhos (Playwright/dvc/quarto) via `os.killpg`. Você não
precisa fazer nada na maioria dos casos.

Se quiser limpar manualmente:

```bash
# Inspecionar o que tá lá
cat .update-all.lock                                                # JSON {parent_pid, child_pids}
ps -p $(.venv/bin/python -c "import json; print(json.load(open('.update-all.lock'))['parent_pid'])") \
    && echo "lock OWNER VIVO — NAO mexer" \
    || rm .update-all.lock
```

### Subprocess órfão

Subprocess do `_stream` rodam em novo process group (`start_new_session=True`)
e ficam registrados no lockfile. Se o Streamlit fechar mid-run, a próxima
execução mata os filhos via `os.killpg(pid, SIGTERM)`. Detached que escaparam
do registro (raro) precisam de cleanup manual:

```bash
pkill -f "scripts/.*-sync.py"
pkill -f "scripts/unify-parquets.py"
pkill -f "playwright"
```

### Histórico de runs

`.pipeline-runs.jsonl` (gitignored, append-only) guarda metadata de cada
execução — sobrevive a restart do Streamlit. Visível em "Recent pipeline
runs" no overview. Sem tails (só status + scope + timestamp). Pra ver
todos:

```bash
cat .pipeline-runs.jsonl | jq -r '"\(.at) \(.scope) \(.stage_status)"'
```

---

## CLI headless (cron / launchd)

Pra rodar o pipeline sem Streamlit — útil pra agendar via cron/launchd:

```bash
# Default: 10 plats que rodam sem browser visivel (sem ChatGPT/Perplexity)
PYTHONPATH=. .venv/bin/python scripts/headless-pipeline.py

# Subset, sem publish
PYTHONPATH=. .venv/bin/python scripts/headless-pipeline.py \
    --plats=Claude.ai,Gemini --no-publish
```

Mesmo lockfile, mesmo gating, mesma persistência em `.pipeline-runs.jsonl`.
Stage 3 também é incremental (renderiza só os qmds das plats sincronizadas
+ cross-overview).

### Agendar com launchd (macOS)

Template em `docs/operations/launchd-headless.plist.template`:

```bash
# 1. Copiar e ajustar o path absoluto
sed "s|PROJECT_ROOT_ABS|$(pwd)|g" \
    docs/operations/launchd-headless.plist.template \
    > ~/Library/LaunchAgents/com.user.multi-ai-pipeline.plist

# 2. Ativar
launchctl load ~/Library/LaunchAgents/com.user.multi-ai-pipeline.plist
launchctl list | grep multi-ai-pipeline

# 3. Logs vao pra data/pipeline-runs/headless.{log,err.log}
tail -f data/pipeline-runs/headless.log

# Desativar:
launchctl unload ~/Library/LaunchAgents/com.user.multi-ai-pipeline.plist
rm ~/Library/LaunchAgents/com.user.multi-ai-pipeline.plist
```

Default agendado: **diário às 03:00**. Editar `StartCalendarInterval` no
plist pra mudar.

---

## Common symptoms and what they mean

| Symptom | Meaning |
|---|---|
| `Discovery: total=1168` | Server shows 1168 convs right now |
| `added=N` in reconcile_log | N new convs captured |
| `preserved_missing=N` | N convs disappeared from the server but are preserved locally |
| `RECONCILER ABORTOU: Queda drastica` | Discovery dropped more than 50% — something is wrong, investigate |
| `Discovery atual=850, baseline=1168 — abortando` | Fail-fast triggered (flaky server, uncommon) |
| Browser opens during capture | Expected on ChatGPT/Perplexity (Cloudflare). Abnormal on the others |
| `ETIMEDOUT` in the log | Network timeout on the server. Try again later |
| `8 assets failed` in download-assets | Expected — 8 assets are irrecoverable (parents long deleted on the server) |

For terminology (`discovery`, `merged`, `baseline`, etc.): see [glossary.md](glossary.md).
