# Perplexity — technical coverage

## Pipeline

- **Pastas cumulativas por conta:** a conta padrao usa `data/raw/Perplexity/`
  e `data/merged/Perplexity/`; as demais usam `account-<n>/` sob essas raizes.
- **Sync orchestrator (2 steps):**
  `python -m src.platforms.perplexity.commands.sync`
  (capture + reconcile). Captures everything in one shot (no separate
  asset step).
- **Capture:** **headed** (Cloudflare 403 in headless — documented by
  design in `perplexity/api_client.py:12-13`).
- **Auth:** persistent profile in `.storage/perplexity-profile-<account>/`
  (generated via `python -m src.platforms.perplexity.commands.login`).

## Coverage

Threads + spaces + pages (inside Bookmarks) + threads in spaces +
space files + assets/artifacts metadata + binary assets + thread
attachments (with `failed_upstream_deleted` manifest for upstream S3
cleanup) + user metadata (info, settings, ai_profile).

Reconciler: full preservation (orphans + ENTRY_DELETED), idempotent.
Output in `data/merged/Perplexity/perplexity_merged_summary.json` +
`LAST_RECONCILE.md` + `reconcile_log.jsonl`.

### Reference volume

- 90 conversations.
- 434 messages.
- 2436 tool_events.
- 90 branches.

### Last validated incremental run — 2026-09-20

Headed capture completed with 82 threads discovered, none fetched and all 82
reused; the three spaces were fetched without errors. All 9 artifact binaries
and 6 thread attachments were already preserved. Reconciliation copied all 82
threads, kept one server-missing space and one orphan marker, and the parser
reproduced the reference volume before the unified parquets and six affected
Quarto reports were regenerated. The asset coverage audit and vault integrity
verification passed. This is a healthy green state: dashboard status must
additionally require a fresh processed parquet, not merely a recent capture
timestamp.

## Canonical parser

Each account tree resolves its immutable catalog UUID into `account_id`; the
legacy `account` label and all existing native IDs remain unchanged.

`src/platforms/perplexity/parser.py`:

- Pages have `conversation_id='page:<slug>'`.
- Search results extracted from `blocks[*].web_result_block.web_results`.
- The canonical asset graph contains one row per native artifact/upload identity.
  Artifacts with a retained binary link to the producing assistant message as
  `output`; native thread uploads link to the user message as `input` even when
  upstream deletion left only manifest evidence. External featured images remain
  references and are not represented as preserved binaries.
- Current coverage is 15 assets and 8 exact message links: 9 artifact binaries
  resolve through the vault, while 6 old uploads remain
  explicitly unavailable with `failed_upstream_deleted`. Signed URLs and errors
  are excluded from processed metadata.
- Nine additional artifact paths were older physical representations
  of those same native outputs: both their upstream `asset_id` and SHA-256 bytes
  match the canonical representation in the same account. They were reported as
  `duplicate_representation` before the retention audit retired their byte copies.
  The asset index and raw pinned
  listing are domain envelopes, not user-facing file outputs.
- Idempotent (~1s to run).

## Descriptive Quarto

`notebooks/perplexity.qmd`: 22MB self-contained HTML.

## UI battery + Chrome MCP probe — gaps closed

- **Thread pin in library:** bug in `list_all_threads` (`seen` as a
  `set` instead of `dict`) discarded `is_pinned: true` when the thread
  already appeared in `list_ask_threads`. Fix: dict-based merge
  propagates the flag.
- **Skills in spaces:** endpoint
  `/rest/skills?scope=collection&scope_id=<UUID>` discovered via probe
  (scope enum: `global`/`organization`/`collection`/`individual`).
  Implemented `list_collection_skills` + `list_user_skills`.
- **Thread archive: Enterprise-only** (see
  [known-limitations.md](../../../known-limitations.md#perplexity)).
- **Voice in Perplexity:** upstream behavior (server transcribes and
  discards audio).

## Server behavior

- Rename bumps `last_query_datetime` (same as ChatGPT).
- Delete via menu = ENTRY_DELETED disappears from everywhere.
- Old threads in a space can become orphans if deleted.

## Related documents

- [Discovery and technical evidence](discovery.md)
- Probes: engineering modules in `src/platforms/perplexity/probes/`.

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.sync
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.parse
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/perplexity.qmd
```

Para uma conta adicional, use um perfil e uma arvore isolados. O parser reune
as arvores e grava o e-mail configurado em `.storage/accounts.json` no campo
`account` dos Parquets:

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.login --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.parse
```

## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Perplexity, reader scope preserves exact
message links for evidenced generated artifacts and retains older uploads as
metadata-only assets when no binary or position is available. See the
[operational transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Explicit login-health check

A one-row `list_ask_threads` request is the established read-only check. It is user-triggered and may require a visible Cloudflare-safe browser. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
