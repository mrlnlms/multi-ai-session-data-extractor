# Gemini — technical coverage

## Pipeline

- **Multi-account** — 2 Google accounts. Profiles in
  `.storage/gemini-profile-{1,2}/` (generated via `scripts/gemini-login.py`).
- **Single cumulative folder per-account:** `data/raw/Gemini/account-{N}/` and
  `data/merged/Gemini/account-{N}/`.
- **Sync orchestrator (3 multi-account steps):**
  `scripts/gemini-sync.py` — capture per-account + assets + reconcile
  per-account. Iterates over both accounts in sequence (default) or
  `--account N` to run just one.
- **Headless capture** (no Cloudflare at runtime).

## Coverage

Conversations + assistant messages + tool events + images
(lh3.googleusercontent.com) + extracted Deep Research markdown reports.

### Reference volume

- 47 + 33 = 80 convs / 560 msgs / 889 tool_events.
- 215 images downloaded + 18 Deep Research markdown reports.
- 8 detected models (2.5 Flash, 3 Pro, Nano Banana, 3 Flash Thinking,
  etc).

## Canonical parser

`src/parsers/gemini.py` + `_gemini_helpers.py`.

The raw schema is **positional** (Google batchexecute, no keys) — paths
discovered via probe (`scripts/gemini-probe-schema.py`):

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
| Share URL | upstream-only — see [LIMITATIONS.md](../../LIMITATIONS.md#gemini) |

## Descriptive Quarto (3 documents)

- `notebooks/gemini-acc-1.qmd` (canonical template, account-1 only).
- `notebooks/gemini-acc-2.qmd` (canonical template, account-2 only).
- `notebooks/gemini.qmd` (consolidated, with stacked bars per account in
  key sections).
- Color: Google blue `#4285F4` (acc-1), darker blue `#1A73E8` (acc-2).

## Related documents

- `docs/platforms/gemini/server-behavior.md` — upstream behavior.
- Probes: `scripts/gemini-probe-schema.py`,
  `scripts/gemini-probe-pin-share.py`.

## Commands

```bash
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py             # both accounts
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py --account 1 # account 1 only
PYTHONPATH=. .venv/bin/python scripts/gemini-parse.py
for f in gemini gemini-acc-1 gemini-acc-2; do
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/${f}.qmd
done
```
