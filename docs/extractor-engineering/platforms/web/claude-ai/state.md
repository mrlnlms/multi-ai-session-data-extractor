# Claude.ai — technical coverage

## Pipeline

- **Per-account cumulative folders:** every durable raw/merged tree uses
  `account-<account_id>/`. The local profile key is resolved from the UUID
  binding; selective sync uses `python -m src.workflows.account_sync
  <account_id> --apply`.
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

### Memory and instruction boundary — owner observation 2026-09-23

- Claude's **Memory** settings expose account memory generated from chats as
  editable/deletable topic records such as Preferences, Profile and other
  topical facts, each with an update date. **Preferences** is a memory topic;
  it is not evidence of a separate account-global instructions surface.
- The same Memory screen exposes distinct project-scoped memory groups and
  editable/deletable topic records within each Project. These are native
  project memories, separate from each project's configured prompt/knowledge.
- The Project UI confirms that separation directly by rendering three
  independent sections side by side: **Instructions** (response guidance),
  **Memory** (what Claude remembers from chats, with its own management entry),
  and **Context** (uploaded project files/capacity). Conversations remain a
  fourth project object. These surfaces must retain separate provenance even
  though Claude combines them while answering inside the Project.
- The observed Project UI also announced migration to a new memory system and
  offered a time-limited export of legacy project memory. This establishes a
  product transition, not permission to replace preserved historical project
  memory with the new representation.
- Account and project memory generation can be enabled, sensitive-topic
  inclusion is controlled separately, and memory import from other AI
  providers is offered. No separate account-global persistent-instructions
  editor was observed.
- The earlier extractor wrote one overwritten `claude_ai_memory.md` string.
  That representation remains preserved as an opaque legacy export; the current
  collector uses the native topic collection described below.

### Native Memory capture and canonical projection — validated 2026-09-25

- Both configured accounts expose `memory_mode=melange`. The Memory screen
  issues `POST /api/organizations/{org}/melange/list` with `{}` and
  `POST /api/organizations/{org}/melange/read` with `{"path": ...}` for a
  topic. `GET /api/organizations/{org}/memory/settings` supplies the mode.
  The older `GET .../memory` still returns one classic Markdown field and is
  not the native topic list.
- The list has native `memory_id`, `path`, `category_id`, `display_name`,
  `description`, `updated_at` and category metadata. Each read has native
  `content`, `version`, `updated_at` and parsed metadata. List identity remains
  authoritative: a read response can return an empty `memory_id`.
- The `projects` category uses `/projects/<project UUID>/...` paths. Other
  categories are account-scoped topics. Project memory is stored as
  `project_memory` with that UUID in `project_key`; it is distinct from each
  project's `prompt_template` and docs. A memory may still be listed for a
  project no longer in the current project listing.
- Normal and discovery-fallback syncs now preserve an immutable per-account
  `_account_memory/melange/<capture>/` snapshot: full list, mode settings,
  every read response and a SHA-256 manifest. All reads and `melange` mode are
  required for a complete snapshot. Partial reads or a mode change cannot mark
  prior topics absent. The previous Markdown file is no longer overwritten.
- Live focused capture returned 130 topics in the default account and 19 in
  the second, with zero read errors: 25 account topics and 124 project topics.
  Canonical parse materialized 149 native topics plus 2 opaque legacy Markdown
  exports, 151 content versions and 300 temporal evidence rows. Unify contains
  these in the shared three memory tables. Native `updated_at` is retained;
  creation is first observation because no native creation field was seen.
  The raw capture and derived Parquets were published in DVC snapshot
  `d3e8d5f` on 2026-09-25.
- Topic edit/delete controls are visible in the UI, but no upstream mutation
  was performed. Future complete lists can establish `is_preserved_missing`;
  the current capture has zero missing topics. The three dated
  `data/external/claude-ai-snapshots` are earlier structured/classic states,
  retained separately from current Melange topics.

### Historical structured snapshots — identity audit (2026-09-25)

The 2026-03-26, 2026-03-30 and 2026-04-18 snapshots can now be attributed to
the **second catalogued Claude.ai account** without owner input. In each
snapshot, `memories.json[0].account_uuid` equals the exported `users.json`
user UUID, and that user's email matches exactly one Claude.ai catalog entry.
The exported Project IDs overlap the raw Project IDs of that account by
82/85, 82/82 and 83/83 respectively, with zero overlap against the other
account. Each `memories.json` contains 38 nonempty Project-memory strings;
all 38 Project scopes also occur in the second account's current Melange
Project-topic listing. Scope/identity overlap does **not** mean that classic
and Melange content are equivalent. The Project strings were unchanged across
these three exports, while the account conversation-memory string changed.

The official Claude parser now reads only their `users.json` and
`memories.json` as a separate historical adapter. It validates exported user
identity against the catalog and projects 39 classic `legacy_export` documents:
38 with their native Project UUID in `project_key` and one account conversation
memory. The three dates produce 41 distinct content versions (the 38 Project
strings did not change; the account string did) and 117 temporal-evidence rows.
The date in each directory is recorded as **day-precision snapshot evidence**,
not as native creation/update time. The adapter does not split classic strings
into invented Melange topics, mark them `preserved_missing`, or overwrite the
current 124 Project topics. The published Claude result now has 190
memory documents, including the 149 current Melange topics and two older
opaque Markdown exports; unify includes the 39 structured historical
documents.

The regular `python -m src.platforms.claude_ai.commands.parse` includes these
snapshots when materialized. `--without-historical` is an explicit opt-out;
missing dated snapshots otherwise fail the parse instead of silently dropping
preserved history. The original exports remain immutable in `data/external/`.
No new owner export or account confirmation is needed. Their other exported
objects, including conversations and Project metadata, are not imported by
this memory adapter and remain preserved as historical source material.
Project Instructions are already retained separately as `prompt_template` in
`claude_ai_project_metadata.parquet` (32 nonempty values among 88 current
Project rows); Project docs/context are separate again. Neither is relabeled
as native Project memory. This projection was published in Git and DVC with
commit `f4e2559`; archive assurance passed after publication.

Binaries + artifacts (code/markdown/html/react via `tool_use`) extracted
during asset download.

Immutable binaries and extracted artifacts are materialized in the central
vault. Raw and merged retain independent mutable JSON and asset manifests.

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
  headless orchestrator enumerates every runnable account from the shared
  inventory and invokes this source command once per account.

### Prior validated collection — 2026-09-12

- A second isolated profile, `account-2`, captured 14 conversations, 3
  projects, and 7 binary files with zero fetch or asset errors.
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
- **Memory topics** in three `claude_ai_agent_memory*.parquet` tables, read
  from verified raw snapshots independently of the merged conversations.

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

## Related documents

- [Discovery and technical evidence](discovery.md)

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

## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Claude.ai, reader scope is the evidenced
message/file or generated-output relationship; text-only inline attachments
remain message content rather than binary assets. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Explicit login-health check

A one-row `chat_conversations_v2` listing is the established read-only check; HTTP 401/403 or `account_session_invalid` means `expired`. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
