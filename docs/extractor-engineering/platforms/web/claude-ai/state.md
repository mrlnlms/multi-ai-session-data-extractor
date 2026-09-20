# Claude.ai — technical coverage

## Pipeline

- **Per-account cumulative folders:** the legacy `default` account remains in
  `data/raw/Claude.ai/` and `data/merged/Claude.ai/`; another profile key uses
  `account-<key>/` below each tree.
- **Sync orchestrator (3 steps):** `python -m src.platforms.claude_ai.commands.sync` (capture +
  assets + reconcile).
- **Headless capture** (no Cloudflare challenge at runtime).
- **Auth:** the default persistent profile is
  `.storage/claude-ai-profile-default/` (generated via
  `python -m src.platforms.claude_ai.commands.login --profile default`). Other profile names follow
  `.storage/claude-ai-profile-<name>/`.

## Coverage

Conversations + projects discovered and captured via standard discovery.
Automatic recovery from transient timeouts via `python -m src.platforms.claude_ai.commands.refetch_known`.

Binaries + artifacts (code/markdown/html/react via `tool_use`) extracted
during asset download.

Immutable binaries and extracted artifacts are materialized in `merged` with
a hardlink when supported, with a normal copy as the cross-filesystem fallback.
Mutable JSON remains independent.

Reconciler v3 (FEATURES_VERSION=2): full preservation (convs +
projects), idempotent. Output: `data/merged/Claude.ai/conversations/<uuid>.json`
+ `projects/<uuid>.json` + `assets/`.

### Latest validated collection — 2026-09-20

- The default profile discovered the same 918 conversations and 5 live
  projects, reused every body without fetch errors, and retained 2 conversations
  plus 79 projects that are no longer listed upstream.
- The explicit `account-2` pass discovered 4 new conversations and 1 new
  project, fetched all five records without errors, and downloaded 1 new binary
  while reusing 7. The combined parser now produces 938 conversations, 26,388
  messages, 17,870 tool events, 1,274 branches, 88 projects, 557 project docs,
  3,567 assets, and 3,618 exact asset links.
- Unify and all 6 selected Quarto reports completed successfully. Vault
  verification covered 22 scopes and 11,749 physical blobs. The general
  headless orchestrator still invokes only the default profile, so additional
  profiles must be run explicitly until account enumeration is implemented.

### Prior validated collection — 2026-09-12

- A second isolated profile, `account-2`, captured 14 conversations, 3
  projects, and 7 binary files with zero fetch or asset errors. Its canonical
  account label is `mrlnlms.me@gmail.com`.
- The combined parser produced 934 conversations, 26,367 messages, 17,792
  tool events, 1,269 branches, and 87 projects.

### Prior validated collection — 2026-08-30

- API session was renewed and validated against the conversation-list endpoint
  before capture. Merely opening a persistent context is not sufficient: an
  expired session can still load the browser while the API returns
  `account_session_invalid`.
- Incremental discovery found 918 conversations and 5 live projects; 65
  conversations and 1 project were fetched, with zero fetch errors.
- Reconciliation added 63 conversations, updated 2, copied 853, and preserved
  2 conversations absent from the current server listing. It retained 84
  projects, including 79 previously preserved records.
- The parser produced 920 conversations, 26,081 messages, 17,634 tool events,
  1,253 branches, and 84 projects. The unified parquets were regenerated.

### Historical reference volume

- ~835 conversations + ~83 projects at the original validation point.
- ~24.5k messages / ~16k tool events / ~1.16k branches.
- ~546 project docs (~23M chars of inline content).

## Canonical parser v3.1

Each account tree resolves its immutable catalog UUID into `account_id`; the
legacy `account` label and all existing native IDs remain unchanged.

`src/platforms/claude_ai/parser.py` + `_parser_helpers.py`.

### Coverage

- **Branches via flat DAG** (`parent_message_uuid` +
  `current_leaf_message_uuid`) — different from ChatGPT's tree-walk. ~28%
  of convs have forks.
- **Thinking blocks** preserved in `Message.thinking`.
- **Tool use/result** → ToolEvent. Observed categories:
  `code_call/_result` (Computer Use/file editing), `artifact_call/_result`,
  `search` (web_search + research), `mcp_*` (Google Drive and others).
- **MCP detection with 3 signals** (`integration_name` + `mcp_server_url` +
  `is_mcp_app`).
- **Attachments with extracted_content** preserved in-place in merged;
  parser records `file_names` in `Message.attachment_names`.
- **Files (binary uploads)** → `Message.asset_paths` resolved from
  `file_uuid`.
- **Canonical file graph** keeps one Asset per native `file_uuid`: user-message
  files are `input`, assistant-message files are `output`, and project files are
  `context`. Extracted artifact versions use `version_uuid` (or an exact
  message/artifact/version locator when the version UUID is absent), link to
  their producing message as `output`, and enrich its `asset_paths`. The current
  two-account base produces 3,566 assets and 3,617 links; 3,292 binaries resolve
  and 274 metadata-only/native file
  records remain visible as unavailable.
- **Inline `attachments` are not binary assets.** Their extracted text remains
  in `Message.attachments_json`. Account-memory exports remain separate domain
  content rather than interaction assets.
- **`is_starred` → `is_pinned`** (cross-platform).
- **`is_temporary`** preserved (ephemeral feature).
- **Project metadata** in `claude_ai_project_metadata.parquet`
  (`docs_count` + `files_count` + `prompt_template`).
- **Project docs** in `claude_ai_project_docs.parquet` (inline content,
  queryable).

### v3.1 gap-fill

- `Conversation.summary` auto-generated by the server (~56% of convs).
- `Conversation.settings_json` per-conv feature flags (100%).
- `Message.citations_json` citations in text blocks.
- `Message.attachments_json` with inline `extracted_content`.
- `Message.start_timestamp` + `stop_timestamp` (per-block latency, ~98%
  coverage, ~30s assistant median).

## Descriptive Quarto

`notebooks/claude-ai.qmd`: 46MB self-contained HTML, render < 30s. Primary
color: Anthropic burnt orange `#CC785C`.

## Validated CRUD scenarios

| Scenario | Coverage |
|---|---|
| Rename | reconciler `test_name_changed_goes_to_use` + real-world use (`updated_at` range ~18 months in the sample base) |
| Delete | reconciler `test_preserved_missing_per_kind` + `test_preserved_marks_flag` (convs and projects) |
| Pin via UI | discovery captures `is_starred` → parser maps to `is_pinned`; 12/835 convs with `is_pinned=True` in the sample base |
| Temporary chat | schema/parser fill `is_temporary` if the server sends it (ephemeral feature — server deletes, rarely persists in merged) |
| Project archive | schema fills `archived_at` if it comes through; scenario still without empirical data (depends on the user archiving a project) |

8 reconciler tests passing + byte-for-byte idempotency validated.

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.sync
# Additional Claude account after one interactive login:
PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.login --profile account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.sync --profile account-2
# If sync left gaps (transient timeouts):
PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.refetch_known
PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.parse
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/claude-ai.qmd
```
## Asset vault transition

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit temporary rollback;
filesystem contents never select the mode. The legacy tree remains preserved,
while the vault reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Claude.ai, reader scope is the evidenced
message/file or generated-output relationship; text-only inline attachments
remain message content rather than binary assets. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Explicit login-health check

A one-row `chat_conversations_v2` listing is the established read-only check; HTTP 401/403 or `account_session_invalid` means `expired`. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
