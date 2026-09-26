# ChatGPT — technical coverage

## Pipeline

- **Per-account cumulative folders:** every durable raw/merged tree uses
  `account-<account_id>/`. Local browser profile keys remain only in the UUID
  binding under `.storage/`; selective sync uses
  `python -m src.workflows.account_sync <account_id> --apply`.
- **Sync orchestrator (4 steps):** `python -m src.platforms.chatgpt.commands.sync` — capture +
  assets + project_sources + reconcile.
- **Capture:** **headed** (Cloudflare detects headless). Project discovery is
  API-first via the sidebar index; DOM is a compatibility fallback only.
- **Auth:** persistent profile in `.storage/chatgpt-profile-<account>/`
  (generated via `python -m src.platforms.chatgpt.commands.login`).
- **Fail-fast against flakey discovery** — `_get_max_known_discovery` recursive
  rglob, 20% threshold (aborts before save if current discovery is <80% of
  the largest historical value).

## Memory and personalization — capture validated locally (2026-09-24)

User-provided screenshots of Settings > Personalization show separate controls
for response style and characteristics, custom instructions and profile fields
(nickname, occupation and "More about you"), and an "Enable memory" switch.
The interface says memory may use chats, files and connected apps, and shows a
"Memory summary" with a Manage action plus a separate link to saved memories.
Settings > Storage lists files and images separately; the screenshots do not
establish that those storage totals represent memory content.

The opened "Memory summary" is a structured narrative with an update indicator,
an "Ask or update" input and "Dive Deeper" links. Its About memory explanation
says ChatGPT automatically remembers information and keeps it up to date, and
that this page is a brief overview rather than a complete list. The screenshots
do not show the complete saved-memory list. The destinations and provenance of
the "Dive Deeper" links are unverified; their appearance alone does not
establish links to source conversations. Personal content visible in the
screenshots is intentionally omitted here.

### Project settings follow-up — owner screenshots and read-only probe (2026-09-25)

The owner showed a new-Project dialog with **Default memory** (the Project can
access memory from outside chats, and vice versa) and **Project-only memory**
(the Project can access only its own memory, hidden from outside chats; the UI
also says Work in the cloud is unavailable for that mode). Later screenshots
of an existing Project showed separate **Instructions**, **Memory** and
**Library access** fields. Its Instructions field was empty, Memory displayed
Default, and opening that field offered both Default and Project-only. This
corrects the initial hypothesis that Project-only was selectable only during
creation. No change was submitted or saved, so persistence of a mode switch
was not tested. The owner noted that the interface had changed that day; these
are observations of that UI, not a timeless product contract.

The Memory selector demonstrates Project memory *scope*, not a list of
individually inspectable Project memories. Project instructions are scoped
response guidance; Library access, Sources/files and chats are distinct
context. The screenshots do not establish a separate native Project-memory
collection, item ID or lifecycle. Personal Project names and contents are
omitted from this maintained record.

The current `fetch_project_files()` already requests
`GET /backend-api/gizmos/{project_id}` but returns only its `files` array;
the rest of the detail response is not preserved by that path. The first
read-only probe used the `default` Playwright profile and received the generic
"Sessao ChatGPT expirou" error for the Project shown by the owner. The client
maps both HTTP 401 and 403 to that message, so the error did not establish a
logout. Chrome browser sign-in and ChatGPT website sign-in are separate.

A follow-up read-only transport check resolved that ambiguity. The UI loaded
seven other Project details through this same GET with HTTP 200 in the
`default` profile; direct browser-page and request-context GETs for one of
those Projects also returned 200. The owner's pictured Project returned **403
under `default`, but 200 under the existing `account-2` profile**. Its
authorized detail response contained `gizmo.memory_scope="global"`,
`gizmo.memory_enabled=true` and an empty string in `gizmo.instructions`; the
same Project displayed Default in the owner's UI. Other observed Project
details used `memory_scope="global"`, and one had nonempty instructions.
The response also contained `files`, but no separate list of Project-memory
items was observed. No Project mutation, sync or raw capture was performed.
The prior failure was a profile/Project access mismatch, not evidence of an
expired ChatGPT login or a generally broken detail endpoint.

Next implementation boundary: preserve Project detail/settings cumulatively
under the correct account, and treat Project instructions as scoped response
guidance while `memory_scope` and `memory_enabled` remain settings metadata.
Do not create/change a Project or promote chats/files to memory to fill the
missing item-list evidence. A Project-only payload value and any independently
inspectable Project-memory item surface remain unobserved. Account saved
memories, summary and Custom Instructions are already captured and projected
as described below.

The extractor calls `GET /backend-api/memories` with
`include_memory_entries=true` and preserves the complete decoded response in
`chatgpt_memories.json`, including unknown fields and native IDs/timestamps.
`chatgpt_memories.md` is a derived readable export. The response from
`GET /backend-api/user_system_messages` remains in `chatgpt_instructions.json`.

Each successful surface capture also writes an immutable snapshot under the
account's raw directory at
`_account_memory/<saved_memories|instructions|summary_checksum|summary>/`.
Each snapshot directory contains the exports and `capture.json`: capture time
in UTC, completeness, request method/path/parameters or JSON body, and SHA-256
hashes. The JSON preserves
the decoded payload, not HTTP wire formatting. Native timestamps remain in
the payload and are not replaced by the capture time. Repeated observations,
including unchanged or explicitly empty memory lists, have separate snapshots.

Before refreshing current exports, their previous bytes are preserved by hash
under `_account_memory/prior_exports/<filename>/<sha256>`. This also protects
pre-existing exports whose original capture date is unknown; no date or native
metadata is reconstructed from those files. Each snapshot is published before
the current exports are individually replaced atomically. Previous snapshots
are never deleted when upstream entries disappear. This is raw historical
evidence; the canonical parser derives per-entry `is_preserved_missing` from
the latest complete saved-memory snapshot.

Surface failures are independent and appear in the capture
report without response bodies. Failed requests and malformed memory-list
responses leave previous exports intact. Account captures also run on the
conversation-discovery fallback, except in dry-run mode. Automated tests cover
lossless fields, updates/removals/empty lists, legacy exports, account isolation,
fetch/write failures, incomplete summary streams and both orchestrator paths.
The parser projects the records into the three existing `AgentMemory` tables,
with distinct kinds for saved entries, summaries, instructions and legacy
exports. See [the memory contract](../../../../product/agent-memory-architecture.md).

The collector loads the summary using
`POST /backend-api/memories/about_you/summary/stream` with an empty JSON body,
matching the observed UI request. It preserves the decoded SSE text as
`chatgpt_memory_summary.sse` and the complete native `done` event payload as
`chatgpt_memory_summary.json`. Unknown fields and `followUps` remain intact;
there is no fixed section count or inferred link to source conversations.
`GET /backend-api/memories/about_you/summary/checksum` is captured independently
before loading the stream, as `chatgpt_memory_summary_checksum.json`; it is an
observation at that time, not a guarantee about the stream's eventual cache
state. No force-refresh flag or memory-edit request is submitted.

Returned streams without a valid, delimited `done` event, or with an error
event, are retained in a summary snapshot with `complete=false`; they produce
a capture error and do not replace the latest complete summary exports.
The protocol's trailing `data: [DONE]` marker is distinct from its structured
`event: done`. SSE comments, CRLF and multiline data are handled.

Focused live collection on 2026-09-24 validated the new writer in both configured
accounts: 132 and 17 saved entries respectively, with native IDs retained,
instructions, checksum and seven summary sections per account. All six current
exports per account matched their snapshot hashes; earlier exports and the
preceding saved-memory/instruction snapshots remained byte-for-byte intact.
The summary source checksum matched the preceding checksum response in both
accounts. This was a memory-only collection; it did not refetch conversations.
The subsequent parser/unify integration materialized these records locally.
The captured data and derived Parquets were published in the DVC snapshot
`d3e8d5f` on 2026-09-25.

### Canonical memory projection (validated 2026-09-25)

Both accounts produce 149 saved-memory documents, two account-instruction
documents and two summaries. IDs include the immutable account UUID; entry
identity uses the native memory ID. Repeated captures reuse content versions,
while retaining separate timestamp/provenance evidence. The parser validates
snapshot hashes, preserves disappeared entries and refuses malformed complete
history. Legacy exports with unknown dates remain queryable without inventing
native IDs or creation dates. The current archive has no distinct-content
changes between the retained observations; change/removal cases are tested
with synthetic fixtures.

The three new ChatGPT outputs are `chatgpt_agent_memories.parquet`,
`chatgpt_agent_memory_versions.parquet` and
`chatgpt_agent_memory_temporal_evidence.parquet`. Unify includes them in the
existing cross-platform memory tables. The dashboard displays counts by kind,
and the ChatGPT Quarto profile includes documents, versions and temporal
evidence. No existing conversation or asset Parquet content changed during
this integration.

The three ChatGPT Parquets reproduce byte-for-byte from the same raw inputs;
their unified rows retain timestamp precision and all raw evidence locators
resolve. Memory-table unification normalizes temporal columns to UTC
nanoseconds to avoid truncation when CLI microsecond columns and null columns
are concatenated with web timestamps.

An authenticated, shape-only browser observation on 2026-09-24 established the
following for the two configured accounts; counts are point-in-time, not a
coverage guarantee:

| UI/network surface | Observed contract |
|---|---|
| Saved-memory entries | `GET /backend-api/memories?include_memory_entries=true` returned 132 entries in one account and 17 in the other. The first entry in each had `id`, `content`, `conversation_id`, `gizmo_id`, `created_timestamp`, `last_updated`, `updated_at`, `status` and `labels` keys. Field presence does not establish non-null values or a verified conversation link. A plain `GET /backend-api/memories` returned an empty `memories` array in the observed UI flow. |
| Memory summary | Opening Manage in the second account caused the UI to call `POST /backend-api/memories/about_you/summary/stream` and `GET /backend-api/memories/about_you/summary/checksum`. The checksum response had `sourceChecksum`, `cachedSourceChecksum`, `cachedGeneratedAtIso` and `isStale` keys. No memory-edit control was submitted. |
| Account instructions | `GET /backend-api/user_system_messages` returned fields for user/about-model messages, name, role, traits and enabled state. Their values were not logged. |

The summary route returned `text/event-stream` in a subsequent observation. Its
events were `started`, `section_types`, seven `section` events, and `done`.
Their JSON payloads exposed `generatedAtIso`, `sourceChecksum`, and structured
`sections` with `id`, `title`, `description`, and optional `followUps` entries
(`preview`, `prompt`, `action`). Seven sections describe this observed response,
not a fixed schema requirement. A subsequent UI check observed the same checksum
response, including its generated timestamp, before and after opening the panel
in one account; `isStale` was false both times. This does not establish behavior
for stale caches. The shape-only observations logged event names, field names,
types and counts, not summary text; later collection preserved the native text
only in the account's raw data.

This directly separates the saved-entry response from the summary-loading
requests in the observed account. The extractor now preserves the original
saved-entry JSON, summary response and checksum separately. The UI's memory
switch and the "Dive Deeper" destinations remain unverified at the endpoint
level. No memory text or credentials were copied into public documentation.

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

- 1276 cumulative conversations: 1208 in the legacy default account and 68 in
  `account-2` (validated 2026-09-20).
- `LAST_RECONCILE.md` and `reconcile_log.jsonl` updated on every run.

## Canonical parser

Each account tree resolves its immutable catalog UUID into `account_id`; the
legacy `account` label and all existing native IDs remain unchanged.

`src/platforms/chatgpt/parser.py` (`ChatGPTParser`, `source_name="chatgpt"`).
Output in `data/processed/ChatGPT/`: conversations, messages, tool_events,
branches, assets, asset_links, agent_memories, agent_memory_versions and
agent_memory_temporal_evidence Parquets.

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
- **Availability** is explicit: the current two-account base produces 1,194
  assets and 1,232 links, with 1,119 local binaries and 75 metadata-only assets.
  All published links and available paths resolve, and no upstream pointer URL
  is published. The parser boundary now commits an authoritative semantic
  appearance snapshot after every web capture. The append-only vault retains
  historical relationships, while the public projection selects the newest
  authoritative snapshot so changed positions do not create stale duplicate
  links.
- Project `_files.json` indexes and Canvas operation records remain preserved
  outside the Asset domain; their reconstructable successful Canvas states are
  Assets. Account memories, summaries and instructions are projected into the
  separate versioned `AgentMemory` domain and are not Assets.
- **Tether quote**, **canvas**, **deep_research**.
- **Custom GPT vs project** distinguished.
- **Preservation** via `is_preserved_missing` + `last_seen_in_server`.

### Current validated volume

1276 convs / 24,478 msgs / 5,507 tool_events. Byte-for-byte idempotent after
the source's volatile server fields are normalized by the pipeline.

### Last validated incremental run — 2026-09-20

Both configured accounts completed headed capture and reconciliation without
discovery errors. The legacy default account discovered 1,205 active
conversations, fetched none, and preserved 3 server-missing records. `account-2`
discovered 66 active conversations, fetched 22, added 21, updated 1, and
preserved 2 server-missing records. Asset capture downloaded 62 conversation
files and 10 project files for `account-2`; 88 conversation-file attempts
remained unavailable upstream and are retained as explicit metadata/evidence.
The run initially exposed 110 missing semantic links under `account-2`: the
incremental writer had preserved delivery, observation and blob records but no
appearance records. The shared web parser boundary now appends those semantic
relationships without rewriting prior evidence. A direct legacy/vault
comparison passes exactly for all 1,194 asset IDs and 1,232 link IDs (961 in
the default account and 271 in `account-2`); the 682 messages with asset paths
also preserve the same ordered payload sequence. Repeated parser output is
byte-for-byte idempotent, the unified base now has 15,109 asset links and
592,066 total rows, all six affected Quarto reports render, the complete test
suite passes, and both coverage and vault integrity verification are green. No
publication was performed in this validation round.

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

- [Discovery and technical evidence](discovery.md)
- [Upstream behavior](server-behavior.md)

## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For ChatGPT, reader scope preserves evidenced
inline/message placements and metadata-only rows; Canvas actions are not
promoted unless they materialize an eligible reconstructable output. See the
[operational transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Explicit login-health check

`GET /backend-api/conversations` is documented, but the current Cloudflare-safe transport requires a visible page. This delivery therefore returns `unknown` instead of opening a browser implicitly. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
