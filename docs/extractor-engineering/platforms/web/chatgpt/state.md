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

Each account tree resolves its immutable catalog UUID into `account_id`; the
legacy `account` label and all existing native IDs remain unchanged.

`src/platforms/chatgpt/parser.py` (`ChatGPTParser`, `source_name="chatgpt"`).
Output in `data/processed/ChatGPT/`: conversations, messages, tool_events,
branches, assets and asset_links Parquets.

### Coverage

- **Full tree-walk** — preserves off-path branches.
- **Voice** with `direction in/out`.
- **DALL-E** mapped as ToolEvent.
- **User uploads** (Message with `image_asset_pointer`).
- **Canonical assets** use native file IDs where available. User pointers become
  `input` links; DALL-E and other tool-file pointers become `output` links.
  User-message block indexes are exact. Tool-only nodes link to the closest
  retained canonical ancestor and keep their native tool-message/block locator
  in metadata; if no ancestor exists, placement degrades to conversation level.
- Project knowledge files use their indexed `file_id` and link to the Project
  as `context`. Canvas operations are replayed branch-by-branch into immutable
  complete states, and these states plus Deep Research reports link to the
  producing message as `output`. Legacy/export images retain only the
  conversation relationship and unknown role when stronger evidence is absent.
- **Canvas replay:** 42 create and 133 update requests are observed. The current
  evidence materializes 149 exact states (37 creates plus 112 updates), all with
  native `textdoc_id`. Fourteen upstream-declared failures produce no state;
  five update requests lack a preserved response; five create requests have no
  usable payload/response in raw and only a truncated legacy representation;
  two successful regex patches cannot be applied to the preceding preserved
  state. These exceptions remain visible as protocol limitations, not invented
  files.
- **Availability** is explicit: the current two-account base produces 1,117
  assets and 1,122 links, with 1,047 local binaries and 70 metadata-only assets.
  All links and available paths resolve, and no upstream pointer URL is published.
- Project `_files.json` indexes and Canvas operation records remain preserved
  outside the Asset domain; their reconstructable successful Canvas states are
  Assets. Account memory exports remain preserved for the separately planned
  memory/configuration domain and are not Assets.
- **Tether quote**, **canvas**, **deep_research**.
- **Custom GPT vs project** distinguished.
- **Preservation** via `is_preserved_missing` + `last_seen_in_server`.

### Typical volume

1255 convs / 22,039 msgs / 4,279 tool_events. Byte-for-byte idempotent after
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
