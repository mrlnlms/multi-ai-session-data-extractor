# ChatGPT — technical coverage

## Pipeline

- **Single cumulative folder:** `data/raw/ChatGPT/` and `data/merged/ChatGPT/`.
- **Sync orchestrator (4 steps):** `scripts/chatgpt-sync.py` — capture +
  assets + project_sources + reconcile.
- **Capture:** **headed** (Cloudflare detects headless). Includes DOM scrape
  of projects + voice pass + auth via cookies.
- **Auth:** persistent profile in `.storage/chatgpt-profile-<account>/`
  (generated via `scripts/chatgpt-login.py`).
- **Fail-fast against flakey discovery** — `_get_max_known_discovery` recursive
  rglob, 20% threshold (aborts before save if current discovery is <80% of
  the largest historical value).

## Validated CRUD scenarios

| Scenario | Result |
|---|---|
| Conv deleted | `is_preserved_missing=True` in merged |
| Conv updated (new msg) | `updated`, `update_time` bumped |
| Conv new | `added` |
| Conv renamed | `updated` (server bumps `update_time`; extra guardrail covers the no-bump edge case) |
| Project created | discovery goes up, new `g-p-*` in `project_sources/` |
| Entire project deleted | sources marked `_preserved_missing`, physical binaries untouched, internal chats preserved |

## Reference volume

- 1171 cumulative conversations (1168 active + 3 preserved_missing).
- `LAST_RECONCILE.md` and `reconcile_log.jsonl` updated on every run.

## Canonical parser

`src/parsers/chatgpt.py` (`ChatGPTParser`, `source_name="chatgpt"`).
Output in `data/processed/ChatGPT/`: conversations.parquet,
messages.parquet, tool_events.parquet, branches.parquet.

### Coverage

- **Full tree-walk** — preserves off-path branches.
- **Voice** with `direction in/out`.
- **DALL-E** mapped as ToolEvent.
- **User uploads** (Message with `image_asset_pointer`).
- **Tether quote**, **canvas**, **deep_research**.
- **Custom GPT vs project** distinguished.
- **Preservation** via `is_preserved_missing` + `last_seen_in_server`.

### Typical volume

1171 convs / 17,583 msgs / 3109 tool_events / 1369 branches. Byte-for-byte
idempotent.

## Descriptive Quarto

- `notebooks/chatgpt.qmd` — "zero spin" data profile: schema + coverage
  + samples + distributions + preservation. No sentiment/clustering/topic.
- Stack: DuckDB + Plotly + itables.
- Output: `notebooks/_output/chatgpt.html` (~52MB self-contained).
- Render: ~20s for ~1k convs.

## Commands

```bash
PYTHONPATH=. .venv/bin/python scripts/chatgpt-sync.py --no-voice-pass
PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
```

Without `QUARTO_PYTHON`, Quarto tries the system python and fails due to
missing deps (duckdb, plotly, itables).

## Related documents

- `docs/platforms/chatgpt/server-behavior.md` — upstream behavior.
