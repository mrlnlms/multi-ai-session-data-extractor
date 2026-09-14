# ChatGPT — technical coverage

## Pipeline

- **Per-account cumulative folders:** the legacy `default` account remains in
  `data/raw/ChatGPT/` and `data/merged/ChatGPT/`; another profile key uses
  `account-<key>/` below each tree.
- **Sync orchestrator (4 steps):** `python -m src.platforms.chatgpt.commands.sync` — capture +
  assets + project_sources + reconcile.
- **Capture:** **headed** (Cloudflare detects headless). Project discovery is
  API-first via the sidebar index; DOM is a compatibility fallback only.
- **Auth:** persistent profile in `.storage/chatgpt-profile-<account>/`
  (generated via `python -m src.platforms.chatgpt.commands.login`).
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

- 1249 cumulative conversations: 1207 in the legacy default account and 42 in
  `account-2` (discovered 2026-09-12).
- `LAST_RECONCILE.md` and `reconcile_log.jsonl` updated on every run.

## Canonical parser

`src/platforms/chatgpt/parser.py` (`ChatGPTParser`, `source_name="chatgpt"`).
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

1249 convs / 21,765 msgs / 4071 tool_events. Byte-for-byte idempotent after
the source's volatile server fields are normalized by the pipeline.

## Descriptive Quarto

- `notebooks/chatgpt.qmd` — "zero spin" data profile: schema + coverage
  + samples + distributions + preservation. No sentiment/clustering/topic.
- Stack: DuckDB + Plotly + itables.
- Output: `notebooks/_output/chatgpt.html` (~52MB self-contained).
- Render: ~20s for ~1k convs.

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.sync --no-voice-pass
# Login and sync an additional account once; its parser output is combined.
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.login --profile account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.sync --account account-2 --no-voice-pass
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.parse
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
```

The optional local `.storage/accounts.json` maps profile keys to the e-mail
written to the canonical `account` field. It does not change upstream
conversation IDs.

Without `QUARTO_PYTHON`, Quarto tries the system python and fails due to
missing deps (duckdb, plotly, itables).

## Related documents

- `docs/extractor-engineering/platforms/web/chatgpt/server-behavior.md` — upstream behavior.
## Explicit login-health check

`GET /backend-api/conversations` is documented, but the current Cloudflare-safe transport requires a visible page. This delivery therefore returns `unknown` instead of opening a browser implicitly. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
