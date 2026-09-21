# Qwen — technical coverage

## Pipeline

- **Pastas cumulativas por conta:** todas as arvores duraveis raw/merged usam
  `account-<account_id>/`. O profile local e resolvido pelo binding do UUID;
  sync seletivo usa `python -m src.workflows.account_sync <account_id> --apply`.
- **Sync orchestrator (2 steps):** `python -m src.platforms.qwen.commands.sync` (capture +
  reconcile).
- **Headless capture.**
- **Auth:** perfis persistentes em `.storage/qwen-profile-<account>/`
  (gerados via `python -m src.platforms.qwen.commands.login --account <account>`). The token may expire even when the
  profile still opens; validate a minimal API list request before a sync.

## Coverage

Chats + projects + project files captured. Reconciler v3
(FEATURES_VERSION=2): full preservation for convs + projects.

### Latest validated collection — 2026-09-20

- The default profile rediscovered the same 144 current chats, 6 projects,
  and 15 project files. It reused all conversation bodies without fetch
  errors, retained 1 preserved-missing chat, downloaded 16 asset
  representations, reused 354, and preserved the 5 URLs still unavailable
  upstream.
- The explicit `account-2` pass grew from 3 to 5 current chats and from 1 to
  2 projects with 7 project files. Both new conversation bodies and all 9
  requested asset representations were captured without errors.
- The round exposed a vault-mode reconciliation bug: Qwen updated the merged
  manifest but skipped the then-required compatibility projection into merged
  whenever an asset reader was active. The immediate parity fix preserved that
  projection in both reader modes. The subsequent vault-only correction stopped
  rematerializing it during normal capture, and the retention audit removed the
  prior byte copy only after proving it in the vault. The parser consequently
  resolves all 372 canonical assets locally and the archive-wide coverage gate
  reports zero eligible-uncovered, unresolved, or broken-link findings.
- The combined parser produces 150 conversations, 2,194 messages, 9 tool
  events, 181 branches, 8 projects, 22 project docs, 372 assets, and 372 exact
  asset links. Unify, all 6 selected Quarto reports, vault verification across
  22 scopes and 11,752 physical blobs, and the complete test suite pass.

### Prior validated collection — 2026-08-30

- The previous token was expired; after interactive login, a one-page API read
  confirmed the renewed authorization before capture.
- Incremental discovery found 144 current chats, 6 projects, and 15 project
  files. No conversation bodies required refetch and there were no fetch
  errors.
- Reconciliation retained 144 current chats plus 1 preserved-missing record
  (145 total); all 6 current projects were retained.
- Assets: 15 downloaded, 355 existing assets skipped, and 5 URLs unavailable
  upstream. Conversation preservation and parsing were unaffected.
- The parser produced 145 conversations, 2,157 messages, 9 tool events,
  175 branches, 6 projects, and 15 project docs; the unified parquets were
  regenerated.

### Additional account collection — 2026-09-12

- A second personal account was captured through its own persistent browser
  profile and isolated raw/merged trees.
- Discovery found 3 current chats, 1 project, and 4 project files. The full
  incremental capture fetched all missing chat bodies without errors and
  downloaded all 4 project files.
- The combined parser output has 148 conversations, 2,188 messages, 9 tool
  events, 179 branches, 7 projects, and 19 project docs. The canonical
  `account` field distinguishes the two accounts by their configured email
  addresses.

### Historical reference volume

- 115 chats / 3 projects / 4 project files at the original validation point.
- 1,799 messages / 9 tool events / 133 branches.

## Canonical parser

Each account tree resolves its immutable catalog UUID into `account_id`; the
legacy `account` label and all existing native IDs remain unchanged.

`src/platforms/qwen/parser.py` + `_parser_helpers.py`.

### Coverage

- **8 chat_types mapped to modes:** chat / search / research
  (deep_research) / dalle (t2i+t2v).
- **Branches via flat DAG** (`parentId`/`childrenIds` + `currentId`).
- **`reasoning_content` → `Message.thinking`** (rare — feature of
  QwQ-style models, conditional).
- **`search_results`** (from `info.search_results` blocks) → ToolEvent.
- **t2i/t2v/artifacts** always emit ToolEvent
  (`image/video_generation`, `artifact`).
- **`pinned` → `is_pinned`** (cross-platform).
- **`archived` → `is_archived`** (but always False — see
  [known-limitations.md](../../../known-limitations.md#qwen)).
- **`meta.tags` + `feature_config`** preserved in `settings_json`.
- **`content_list[*].timestamp`** → `Message.start_timestamp`/`stop_timestamp`.
- **Project with `custom_instruction`** + `_files` (presigned S3 URLs,
  expire in 6h) → `project_metadata` + `project_docs` parquets.

## Integrated asset download

`python -m src.platforms.qwen.commands.download_assets`. URLs in msgs/projects downloaded via
manifest. Parser resolves `asset_paths` via `assets_manifest.json` and publishes
the canonical `assets` plus `asset_links` contracts. Native `file_id` identifies
uploads and project sources; generated files without an upstream ID use their
preserved SHA-256 content identity. Rotated signed URLs therefore do not create
duplicate assets and are never copied into processed metadata.

The current archive materializes 372 distinct assets: 294 user uploads, 56
assistant-generated outputs, and 22 project sources. Each has one evidenced
link: uploads and generated outputs resolve to their exact input/output message,
while project files resolve to the matching `ProjectDoc` with `role=context`.
All 372 Asset rows carry a locally resolving path, subject to the collision
qualification below. Seven additional PNG paths are verified
same-account, byte-identical physical copies of generated outputs whose canonical
identity is already their SHA-256 content digest; the coverage audit reports
them as `duplicate_representation`, not missing Assets. Existing
`Message.asset_paths` and `ProjectDoc` rows remain intact for compatibility and
domain-specific analysis.

The Task 7 identity invariant exposed and closed a separate historical
collision: 104 native upload identities in the default account's manifest had
reused 11 physical paths. The downloader now keeps the readable filename plus
a deterministic hash of the stable native `file_id`, so rotated URLs reuse the
same destination while distinct IDs cannot collide. A recovery run wrote 293
collision-safe files without overwriting the legacy tree; this included every
identity in the 11 ambiguous groups. The manifest retains old-path lineage.
Two separately recaptured, byte-identical uploads shared one legacy text path;
that old copy and 199 other byte-proven legacy paths are reported as duplicate
representations. Together with the seven generated-output duplicates described
above, Qwen now has 367 covered canonical Assets, 207 verified physical
duplicates, zero eligible-uncovered and zero unresolved findings.
This source result contributes to the green nine-source gate that publishes the
archive-wide `preserved_web_files` scope; the 207 physical duplicates remain
preserved and are accounted for rather than silently removed.

## Descriptive Quarto

`notebooks/qwen.qmd`: 17MB HTML, render < 30s, primary color purple `#615CED`.

## Validated CRUD scenarios

| Scenario | Result |
|---|---|
| Rename | title matches in parquet, `updated_at` bumps |
| Pin | `is_pinned=True`, `updated_at` bumps |
| Archive | upstream no-op on Pro/free (see [known limitations](../../../known-limitations.md#qwen)) |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preserved |

## Related documents

- [Discovery and technical evidence](discovery.md)
- [Upstream behavior](server-behavior.md)

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.sync
PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.parse
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/qwen.qmd
```

Para uma conta adicional, use um perfil e uma arvore isolados; o parser reune
as arvores e registra o email configurado em `.storage/accounts.json` no campo
`account` dos Parquets:

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.login --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.parse
```

## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Qwen, reader scope preserves evidenced
inline message/project uses and their ordering; duplicate representations do
not create duplicate asset identities or overwrite the legacy tree. See the
[operational transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Explicit login-health check

A one-page `GET /api/v2/chats/` listing is the established read-only check; an upstream authentication rejection means `expired`. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
