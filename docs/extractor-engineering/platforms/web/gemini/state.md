# Gemini — technical coverage

## Pipeline

- **Multi-account** — 3 Google accounts. Profiles in
  `.storage/gemini-profile-{1,2,3}/` (generated via
  `python -m src.platforms.gemini.commands.login`).
- **Single cumulative folder per-account:** `data/raw/Gemini/account-{N}/` and
  `data/merged/Gemini/account-{N}/`.
- **Sync orchestrator (3 multi-account steps):**
  `python -m src.platforms.gemini.commands.sync` — capture per-account + assets + reconcile
  per-account. Iterates over all active accounts in sequence (default) or
  `--account N` to run just one.
- **Headless capture** (no Cloudflare at runtime).

## Coverage

Conversations + assistant messages + tool events + images
(lh3.googleusercontent.com) + extracted Deep Research markdown reports.
Immutable assets are hard-linked into `merged` when supported, with a normal
copy fallback; mutable conversation JSON remains independent.

### Latest validated collection — 2026-08-30

- Accounts 1 and 2 reauthenticated, then collected incrementally.
- Discovery: account 1 found 50 conversations (16 fetched, 34 reused);
  account 2 found 34 (all reused); neither had fetch errors.
- Reconciliation preserved records no longer listed by Gemini: 15 in account 1
  and 2 in account 2. The merged corpus now parses to 101 conversations,
  758 messages, and 1,742 tool events.
- Account 1 asset download saved 114 new assets and skipped 54 existing ones;
  73 image URLs returned HTTP 403 and remain unavailable upstream. Account 2
  assets were left unchanged during this run after its incremental capture.
- `python -m src.platforms.gemini.commands.reconcile` is again usable with the current
  `data/raw/Gemini/account-{N}` layout. It supports `--full`; there are no
  Gemini-specific feature-refetch flags.
- The standalone `download_assets` and `reconcile` helpers resolve that same
  cumulative account root directly; only the historical `merge_timestamps`
  utility still targets the pre-pipeline `data/raw/Gemini Data/` archive.

### Third account — 2026-09-12

- Account 3 uses its own browser profile, raw/merged trees, and canonical
  `account-3_{uuid}` conversation-ID namespace.
- The parser discovers every numeric `account-N` tree under the merged root;
  the sync and auxiliary commands accept accounts 1, 2 and 3.
- The first collection found and fetched 1 conversation without errors. It had
  no downloadable images or Deep Research reports. The combined parser now
  has 102 conversations, 760 messages, and 1,742 tool events.

### Historical reference volume

- 47 + 33 = 80 conversations / 560 messages / 889 tool events at the original
  2026-05 validation point.
- 215 images downloaded + 18 Deep Research markdown reports at that point.
- 8 detected models (2.5 Flash, 3 Pro, Nano Banana, 3 Flash Thinking,
  etc).

## Canonical parser

`src/platforms/gemini/parser.py` + `_parser_helpers.py`.

The raw schema is **positional** (Google batchexecute, no keys) — paths
discovered via probe (`src/platforms/gemini/probes/schema.py`):

- `turn[2][0][0]` → user text.
- `turn[3][0][0][1]` → assistant text (chunks).
- `turn[3][21]` → model name.
- `turn[3][0][0][37+]` → thinking blocks (heuristic >=200 chars excl.
  main response).
- `turn[4][0]` → timestamp epoch secs.

### Coverage

- ~41% of assistant msgs with thinking.
- **Image generation** via regex over the turn's JSON → ToolEvent +
  `Message.asset_paths` resolved via per-account `assets_manifest.json`.
- **Multi-account with `account-{N}_{uuid}` namespace** in
  `conversation_id`.
- **Search/grounding citations** (Search + Deep Research) — 1 ToolEvent
  `search_result` per citation, deduped by URL; also populate
  `Message.citations_json`.

## Validated CRUD scenarios

| Scenario | Result |
|---|---|
| Rename | title matches in parquet |
| Pin | `is_pinned=True` (discovered via probe — field `c[2]` of the MaZiqc listing returns `True` when pinned, `None` otherwise) |
| Delete | `is_preserved_missing=True`, title + `last_seen` preserved |
| Share URL | upstream-only — see [known limitations](../../../known-limitations.md#gemini) |

## Descriptive Quarto (3 documents)

- `notebooks/gemini-acc-1.qmd` (canonical template, account-1 only).
- `notebooks/gemini-acc-2.qmd` (canonical template, account-2 only).
- `notebooks/gemini-acc-3.qmd` (canonical template, account-3 only).
- `notebooks/gemini.qmd` (consolidated, with stacked bars per account in
  key sections).
- Color: Google blue `#4285F4` (acc-1), darker blue `#1A73E8` (acc-2), and
  Google green `#0F9D58` (acc-3).

## Related documents

- `docs/extractor-engineering/platforms/web/gemini/server-behavior.md` — upstream behavior.
- Probes: `src/platforms/gemini/probes/schema.py`,
  `src/platforms/gemini/probes/pin_share.py`.

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.sync             # all accounts
PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.sync --account 1 # account 1 only
PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.parse
for f in gemini gemini-acc-1 gemini-acc-2 gemini-acc-3; do
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/${f}.qmd
done
```
