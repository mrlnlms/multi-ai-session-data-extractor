# Gemini — technical coverage

## Pipeline

- **Multi-account** — three compatibility-default Google accounts. Profiles in
  `.storage/gemini-profile-<key>/` (generated via
  `python -m src.platforms.gemini.commands.login`).
- **Single cumulative folder per-account:** durable trees use
  `data/raw/Gemini/account-<account_id>/` and
  `data/merged/Gemini/account-<account_id>/`. The compatibility profile key is
  local binding state; selective sync uses
  `python -m src.workflows.account_sync <account_id> --apply`.
- **Per-account sync command (3 steps):**
  `python -m src.platforms.gemini.commands.sync --account <safe-key>` — capture
  + assets + reconcile for exactly one account. The shared headless workflow
  enumerates every runnable account from the inventory and invokes this command.
- **Headless capture** (no Cloudflare at runtime).

## Coverage

Conversations + assistant messages + tool events + images
(lh3.googleusercontent.com) + extracted Deep Research markdown reports.
Immutable asset bytes are written to the central vault. Raw and merged retain
their independent conversation JSON and asset manifests.

### Instructions discovery checkpoint — 2026-09-23

- Account-level **Instructions for Gemini** are exposed by batchexecute RPC
  `ZKcapf` with read payload `[100]` on the `/saved-info` surface.
- A controlled item demonstrated a positional native envelope with stable
  identity, content, temporal fields, and state/type fields. Its reuse in a
  separate conversation was also observed; a conflicting per-message request
  could override the persistent instruction.
- `GeminiAPIClient.list_instructions()` performs this read and the account
  capture stores the untouched native list envelope under
  `instructions/snapshots/<sha256>.json`. An append-only
  `instructions/observations.jsonl` records every observation; identical
  payloads reuse their content-addressed snapshot, and a later empty state
  cannot remove a prior non-empty one.
- A live account-1 capture on `2026-09-23` durably retained the controlled
  item and verified the snapshot filename against its payload hash.
- After the owner deleted that controlled item upstream, a second live capture
  stored the empty native envelope as a distinct snapshot and retained the
  original non-empty snapshot byte-for-byte. The two append-only observations
  validate the intended Instructions lifecycle preservation.
- On `2026-09-25`, isolated read-only captures of all three accounts returned
  explicit empty lists. They added account-2 and account-3 observations without
  changing conversation captures; account-1's earlier non-empty snapshot was
  retained.
- This surface is distinct from conversation-derived **Memory**, whose
  readable transport remains unresolved.

### Conversation-derived Memory transport checkpoint — 2026-09-23

- A read-only account-1 probe compared the network activity of
  `/personalization-settings` and `/saved-info` without sending a message or
  changing account state. It retained only response hashes, sizes, container
  shapes, and public navigation metadata; response scalar values and request
  bodies were not persisted.
- The Personal Intelligence page produced no exclusive batchexecute RPC. Its
  RPC set was the shared Gemini bootstrap/configuration set. The Instructions
  page produced one additional RPC, the already identified `ZKcapf` list
  transport.
- No response loaded by either surface contained a literal English `memory`,
  `past chats`, or `saved-info` indicator. The Personal Intelligence page
  still rendered the enabled Memory control, so the control can be delivered
  through page/bootstrap state without exposing a readable list of learned
  memory items.
- This observation does **not** prove that Gemini stores no conversation-
  derived memory. It establishes only that no separate readable memory-item
  envelope was observed on either account-management surface. Conversation-
  derived personalization without a user-inspectable record or stable native
  payload is outside the extractor's preservation scope; do not reconstruct
  inferred memories from answers or continue behavioral transport probing.
- The reproducible structural probe is
  `src/platforms/gemini/probes/personalization_transport.py`. Its reports are
  local runtime diagnostics under `.runtime/probes/`, outside the preserved
  raw archive.

### Canonical Instructions projection — 2026-09-25

- Instructions are an approved routine raw-capture surface, not a pending
  experiment. Normal account capture reads the native envelope and preserves
  its cumulative lifecycle even when the current upstream list becomes empty.
- Instructions are `persistent_instructions`, not learned `native_memory`.
  ChatGPT and Qwen now establish equivalent account-global instruction scope;
  the existing `account_instructions` kind projects each Gemini item separately
  by native ID into the three versioned `AgentMemory` tables. Project prompts
  remain `project_context`.
- The parser verifies every snapshot hash and the observed positional list
  shape before interpreting it. Only a verified complete empty list marks a
  previously seen item `is_preserved_missing`; invalid or partial responses
  fail closed. The account-1 controlled item is currently preserved-missing,
  with one immutable version. Accounts 2 and 3 have no materialized items.
- The two native timestamp pairs are retained as positional temporal evidence
  (`field_2` and `field_4`); their creation/update semantics have not been
  independently established. Canonical effective dates therefore use capture
  observations, not guessed native semantics. The native response, including
  other state/type fields, stays untouched in raw.

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

### Canonical asset validation — 2026-09-14

- The current merged corpus parses to 105 conversations, 770 messages and
  1,746 tool events.
- 350 image-manifest entries plus content-deduplicated Deep Research reports
  produce 364 available assets across two accounts: 173 assistant-origin, 110
  user-origin and 81 unknown-origin rows.
- The parser emits 963 unique message links (787 input and 176 output). Every
  asset/message relationship resolves, repeated parses are byte-identical, and
  neither canonical asset table contains signed source URLs.

### Preserved-file audit closure — 2026-09-15

- At this checkpoint, all 391 physical files under the per-account merged asset
  trees were accounted for: 364 canonical available assets and 27 additional physical
  representations of those same content identities.
- The 27 duplicates comprise 25 hosted images and 2 Deep Research Markdown
  reports. Each matches a canonical file byte for byte inside the same account;
  filenames and timestamps are not used as duplicate evidence.
- The duplicate files were preserved at this checkpoint. The audit classified them as
  `duplicate_representation`, so Gemini has zero eligible-uncovered and zero
  unresolved file representations without creating duplicate Asset rows.
- The later retention audit removed those byte copies after proving their
  content identities in the vault; their manifest evidence remains preserved.
- Two temporary parses were byte-identical to each other and to the current
  five processed Gemini tables. All 364 available paths and all asset/message/
  conversation relationships resolve.

### Operational validation — 2026-09-20

The three-account headless pipeline completed capture, reconciliation, parse,
unify, and all 9 selected Quarto renders without publication. Discovery found
the same `50 + 34 + 1` current conversations, reused all 85 bodies, and had no
conversation fetch errors. Reconciliation retained 18 and 2 conversations no
longer present in the account-1 and account-2 listings. The 73 expired
account-1 image URLs still return HTTP 403 and remain preserved as unavailable
upstream evidence; accounts 2 and 3 had no asset download errors.

The first vault-mode parse exposed a representation-path mismatch: Gemini
content-deduplicates identical image bytes into one canonical `Asset`, while a
message could still carry the filename of another preserved representation.
The parser now resolves each image message path through the representation's
content identity and replaces it with the canonical asset path, without
removing either physical representation. A regression test covers two
filenames with identical bytes. The clean repeat produced 105 conversations,
770 messages, 1,746 tool events, 733 vault assets (660 available and 73
reference-only), and the same 963 exact asset links. Vault verification covered
22 scopes and 11,748 physical blobs, and the complete repository suite passed.

## Canonical parser

Each account tree resolves its immutable catalog UUID into `account_id`; the
legacy `account` label and all existing native IDs remain unchanged.

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
- **Canonical assets** — manifest images and extracted Deep Research Markdown
  are content-deduplicated within each account into `assets.parquet`. Each
  distinct observed turn use is represented in `asset_links.parquet`: user
  blocks are `input`, assistant blocks are `output`, and the sidecar
  `source_path` locates reports at the exact user or assistant message when
  available. Manifest objects without a surviving reference remain visible as
  unlinked assets with unknown origin. Signed source URLs are never copied into
  either asset table.
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

- [Discovery and technical evidence](discovery.md)
- [Upstream behavior](server-behavior.md)
- Probes: `src/platforms/gemini/probes/schema.py`,
  `src/platforms/gemini/probes/pin_share.py`.

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.workflows.headless --plats=Gemini --no-publish # all runnable accounts, then one parse
PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.sync --account 1     # direct account sync, no parse
PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.parse
for f in gemini gemini-acc-1 gemini-acc-2 gemini-acc-3; do
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/${f}.qmd
done
```

## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Gemini, reader scope preserves each
evidenced turn use, including repeated appearances, while unpositioned manifest
entries remain assets without fabricated message links. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Explicit login-health check

A single `MaZiqc` conversation listing is the established read-only check; a successful parsed response is the only path to `valid`. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
