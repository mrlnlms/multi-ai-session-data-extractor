# Roadmap

This is the operational index for outstanding work and important completed
decisions. It intentionally links to the evidence and technical detail rather
than duplicating it here. Completed work is marked here so its status can be
read without searching Git history; implementation detail belongs in `git log`,
and platform-specific behavior belongs in its own documentation.

**Last reviewed:** 2026-09-15.

For one-time work, use **planned**, **active**, or **completed**. Mark completion
when closing the work, with its date and an evidence pointer when available.
Ongoing operations and future exploration can use descriptive statuses instead.
This index is the normal signal for planning; check observable state when it
conflicts with the entry or the task requires a fresh verification.

## Current operational state

| Item | Status | Evidence | Next safe action |
|---|---|---|---|
| DVC Google Drive remote | Active operational remote | [DVC runbook](operations/dvc-runbook.md) | Use it to publish and recover the canonical current dataset. |
| Capture and processing | Unblocked | [AGENTS.md](../AGENTS.md) | Run the normal sync → parse → unify pipeline when updating a source. |
| DVC garbage collection | Deliberate storage maintenance | [DVC runbook](operations/dvc-runbook.md) | Simulate, review and explicitly authorize it after a validated publication. |

Google Drive remains the active remote while alternatives are researched. This
is not an active migration or a freeze of the normal capture/publish workflow.

## Current alignment and planning horizon

### Development line behind the current work

The recent restructuring is one product transition, not a collection of
unrelated cleanup tasks: move preservation, account identity, pipeline
execution and archive-reading contracts into reusable `src/` services and
canonical data, while keeping Streamlit and Quarto as consumers. Streamlit is
the current operational presentation adapter, not the product core. Standard
Quarto profiles are current descriptive surfaces, not a required future
frontend; authorial/exploratory notebooks remain useful. The target is one
local-first archive application, but no replacement shell has been chosen and
neither current surface should be removed before its function has a validated
replacement. See the [product architecture map](product/README.md),
[product vision](product/product-vision.md) and the selective
[development evidence map](product/development-evidence-map.md) for the
specific plans and records behind this transition.

The boundary already established is: source-specific capture/reconciliation/
parsing in `src/platforms/`; UI-neutral observation and profiles in
`src/application/`; pipeline ordering, locks and publication in
`src/workflows/`; the dashboard in `dashboard/` for Streamlit presentation.
The durable account catalog and published `account_id` provenance are also
part of this foundation. The unified `assets` and `asset_links` tables provide
asset identity, available paths and evidence-backed relationships. Their
published coverage has defined web and CLI scopes, while placement precision
varies by source; reader behavior still needs validation with real content.
These are architectural baselines or partial contracts, not a queue to redo
completed refactors. The [account architecture](product/account-architecture.md) and
[reader/identity contract](product/reader-and-identity-contract.md) carry the
details only when a task needs them.

The near-term fronts below extend this reusable domain and data contract,
not features inside Streamlit or static Quarto reports. Read this section first
for product alignment; open a detailed document only for the active question.

The near-term data-layer fronts are the preserved ChatGPT/Claude.ai
account-memory/configuration domain, a derived account dimension in unified
data, and a central physical home for preserved asset binaries. The account
dimension continues the already-published `account_id` work: it would expose
the durable catalog as queryable, read-only data without making Parquet the
account registry or inferring CLI/manual identities. The asset front continues
the published per-source identity and relationship work: the Parquets already
follow clear pipeline stages, while binaries remain distributed across source
trees in `raw` and `merged`. A central store and preservation manifest should
replace that fragmented physical layout and its source-specific path handling,
not add another parallel layer. `assets`/`asset_links` remain published outputs
whose fields and IDs may be reviewed as the capture-to-analysis contract is
designed; source provenance must remain explicit. These fronts are concurrent
planning priorities, not a fixed
implementation order; schema changes and data publication retain their normal
review and validation gates.

The memory evidence is in [known limitations](extractor-engineering/known-limitations.md)
and the [ChatGPT](extractor-engineering/platforms/web/chatgpt/state.md) and
[Claude.ai](extractor-engineering/platforms/web/claude-ai/state.md) state records.
The account dimension starts from [`src/account_catalog.py`](../src/account_catalog.py)
and the current [`unify` table contract](../src/workflows/unify.py); historical
working plans in `private/` must be checked against current code before reuse.
The asset layout starts from the [original vault proposal](#physical-asset-layout),
the [published coverage contract](extractor-engineering/asset-coverage.md) and
the current code, rather than treating any one of them as an unchangeable final
design.

Cross-session archive assurance now has a local record in
`.runtime/archive-assurance.json`. A deliberate verification checks local
pipeline freshness, DVC working data, DVC cache/remote sync and the published
Git revision, then saves a compact baseline. The normal publish pipeline saves
the same baseline after successful `dvc add`, `dvc push` and `git push`. A new
Codex session receives only one line from that record; it checks for local
changes without repeating a remote query or filling the agent context with an
audit. Details and explicit re-verification remain available through
[`src.operations.archive_assurance`](../src/operations/archive_assurance.py).

The archive reader is a future product front, likely before any DVC remote
change. Research or migration of the remote is later storage work; the asset
layout is near-term and independent of that remote decision. Neither storage
front is a prerequisite for the reader.
This section records planning emphasis, not an implementation sequence or
authorization to start work during an alignment conversation.

## Product evolution reading map

This is the short index for humans and agents working on the archive product.
Read only the documents required by the question at hand; platform-specific
behavior remains in each platform's own documentation.

| Question | Authoritative document | Role |
|---|---|---|
| How do today's dashboard and Quarto surfaces evolve into one application? | [product/README.md](product/README.md) | Product architecture map and transition boundaries. |
| Where are the related private plans and records, without reading them all? | [product/development-evidence-map.md](product/development-evidence-map.md) | Selective evidence by theme and execution state; not a second work queue. |
| What product is this becoming, and what remains deliberately open? | [product/product-vision.md](product/product-vision.md) | Product vision; not a spec. |
| What is the current priority and what work is operationally pending? | This roadmap | Ordering and status. |
| How should IDs, references and non-message events be interpreted? | [product/reader-and-identity-contract.md](product/reader-and-identity-contract.md) | Technical record for the reader and future curation. |
| How might account instances, application packaging and local authentication fit together? | [product/account-architecture.md](product/account-architecture.md) | Paused architectural exploration with explicit open decisions; not an implementation spec. |
| What is the canonical capture and processing contract? | [AGENTS.md](../AGENTS.md) and [`src/schema/models.py`](../src/schema/models.py) | Agent instructions and observable schema. |
| What does a particular source currently capture or miss? | [platform engineering records](extractor-engineering/platforms/README.md) and [known limitations](extractor-engineering/known-limitations.md) | Per-source evidence and known gaps. |
| How is the existing dashboard operated? | [operations/dashboard.md](operations/dashboard.md) | Current operational UI. |
| Where is the complete documentation index? | [README.md](README.md) | Documentation catalog. |

Future designs and specs should be linked from this map when created, rather
than being discoverable only by filename or Git history.

## Strategic direction — personal AI archive

The project is evolving from an extractor plus analytical dashboard into a
local-first archive of personal AI interactions. The captured archive remains
read-only; operational and curatorial state lives in a separate mutable layer.
This direction does not weaken the preservation contract: `raw` retains
capture evidence, `merged` retains reconciled history, and the Parquets remain
the analytical interface.

The relationship between the current `dashboard/` and `notebooks/` surfaces,
the future unified application, and Quarto's residual analytical role is mapped
in the [product architecture index](product/README.md).

The intended recovery contract is:

```text
Git repository (code + .dvc pointers) + one verified DVC object remote
    = recreate the project data at the matching Git revision with dvc pull
```

Browser profiles and cookies in `.storage/` are deliberately outside that
contract and require a new login after a clean-machine restore. A clean restore
must be demonstrated before retiring any previous remote.

If a future alternative proves viable, the target is a **single** object
remote, not a permanent Drive + R2 arrangement. Until then, Drive remains the
canonical operational remote.

### Storage design work

| Work item | Status | Intended outcome |
|---|---|---|
| Evaluate a single DVC object remote | Future research, not near-term | Remove DVC objects from personal Google Drive without reducing the archive merely to fit an arbitrary free tier. |
| Oracle Object Storage proof of concept | Candidate, not approved | Test a private S3-compatible Oracle bucket. Its published Always Free allocation is 20 GB and 50,000 Object Storage API calls/month; DVC's real request count must be measured before choosing it. |
| [Central asset vault and manifest](../private/docs/discussions/central-asset-vault-alignment-2026-09-15.md) | Near-term data-layer design and validation | Replace distributed binary copies and per-source path handling with one physical home and a preservation manifest; review how the published asset Parquets derive from it, then validate local space, incremental capture and clean restore. |
| Retention audit for `data/external/` | Planned | Classify each set as active input, unique recovery evidence, or verified duplicate before any storage-policy change. |

References: [Oracle Always Free Object Storage](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
[Oracle S3 Compatibility API](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/s3compatibleapi.htm), and
[DVC S3-compatible remotes](https://doc.dvc.org/user-guide/data-management/remote-storage/amazon-s3).

#### Proposed remote evaluation sequence

1. Create an isolated, private candidate remote; do not modify the current
   Google Drive remote.
2. Push and pull a bounded test set, recording storage size, Object Storage
   API requests, and DVC behavior.
3. Demonstrate a clean restore in an empty directory using only Git, local
   credentials stored outside the repository, and the candidate remote.
4. If the proof of concept meets the recovery and free-tier requirements,
   migrate the current required DVC objects and repeat the clean restore.
5. Retire Drive only after explicit approval. Decide separately whether older
   DVC history stays available or the new remote is intentionally a
   current-state archive.

#### Physical asset layout

The published `assets` and `asset_links` tables already provide canonical file
identity, available paths and evidence-backed relationships across sources.
That work makes a physical layout evaluation possible without rediscovering
asset identity. Binary copies in `raw` and `merged` remain preservation inputs;
reconcilers link immutable files when possible. The private
[storage maintenance architecture](../private/docs/discussions/storage-maintenance-architecture.md)
documents that link-at-reconcile rule, while the
[unified assets implementation plan](../private/docs/discussions/unified-assets-implementation-plan.md)
deliberately kept binaries in cumulative `raw`/`merged` trees. Neither is an
implementation plan for a vault. The vault proposal predates the published
`Asset`/`AssetLink` contract: its manifest would record source record/output
identity, MIME, size, content hash, name, capture time and central path. The
design question is how one preservation manifest replaces current per-source
manifests, physical duplicates and path resolvers, with `assets`/`asset_links`
derived as analytical outputs rather than maintained as competing truth.
Physical byte identity and upstream object identity can differ when the same
bytes appear in multiple source contexts; final IDs and fields should be
chosen from observed cases, not frozen around today's schema. This can improve
layout legibility even if APFS clone sharing makes disk savings small. A bounded
local probe found byte-identical `raw`/`merged` samples across seven sources;
an APFS reflink
clone consumed no additional observable space while an ordinary 46 MiB copy
consumed 46 MiB. Physical savings in the current checkout remain unmeasured.
Validate incremental capture, idempotency, published paths and clean restore
before migration. This front is independent of the remote choice and does not
block the reader.

### Archive reader product

**Status:** future product exploration. It does not need to wait for a storage
remote decision.

The reader is currently the clearest product gap: collection and analytical
access exist, but the preserved messages themselves cannot be inspected
comfortably. It also becomes a feedback surface for finding capture, parser,
schema and presentation gaps that remain invisible in aggregate dashboards.

The current Streamlit UI is a replaceable presentation adapter. Platform
observation and data-profile services live under `src/application/`; pipeline
order, gating, locks and optional publication live under `src/workflows/`.
Account management, dynamic replacements for standardized Quarto profiles and
separate publication controls remain product work, not behavior implied by
this refactor.

Build a local-first, read-only reader area beyond the current operational
Streamlit views:

- conversation list, source filters and search in a sidebar;
- selected conversation rendered as a chat timeline;
- branches, citations and tool events shown as contextual details;
- assets rendered from current `assets`/`asset_links` references, according to
  each source's observed relationship precision; and
- source-specific metadata available without exposing the personal archive to
  a public backend.

The first design should start from the existing unified Parquets and locally
available asset paths. CLI timelines need
explicit treatment for thinking, tool calls/results, trajectory steps and
events without canonical messages. The relevant identity and fidelity findings
are recorded in
[product/reader-and-identity-contract.md](product/reader-and-identity-contract.md).

Reading real conversations may reveal missing content, over-grouped events or
relationships that aggregate views cannot expose. Investigate each observed
case against its source's capture, parser and presentation evidence before
changing the canonical archive. Per-source coverage records in
[known limitations](extractor-engineering/known-limitations.md) and the
[platform engineering records](extractor-engineering/platforms/README.md) are
references for that investigation, not a product work sequence.

### Product fronts and architectural emphasis

This describes the intended product architecture, not the current work queue
or a requirement to finish one front completely before touching another:

| Front | Architectural role | Why |
|---|---|---|
| Archive and reader | Reading experience | Closes the visibility gap and reveals fidelity issues in real conversations. |
| Operation and health | Operational experience | Evolves the existing Streamlit capabilities for accounts, logins, runs and diagnostics. |
| Assisted curation | Iterative experience | Depends on reading context and on durable references. |

Parser and schema refinements should be made incrementally when the reader
provides concrete evidence. A full anticipatory rewrite of all sources is not a
prerequisite.

## Decisions requiring explicit direction

| Decision | Why it is not automatic | Evidence | First step once chosen |
|---|---|---|---|
| Evaluate an alternative DVC object remote | It changes storage provider, cost, request limits and the recovery contract. Previous options did not meet the practical cost and retention requirements. | [DVC runbook](operations/dvc-runbook.md) and [storage design work](#storage-design-work) | Reopen research only when a viable alternative exists; Drive remains operational meanwhile. |
| Change the unified schema or publish changed unified data | It can change the published data contract. | [AGENTS.md](../AGENTS.md) and [`src/schema/models.py`](../src/schema/models.py) | Review affected outputs and validate the publication deliberately. |
| Automate deletion of conversations upstream | A selection bug could irreversibly delete the wrong server-side conversations. | [ChatGPT capture-delete cycle](#chatgpt-capture-delete-cycle) | Keep this manual unless a future need justifies automation. |

## Operational work

### Reactivation and compatibility cycle

**Status:** completed on 2026-09-15. The capture and DVC update were validated
and published; the local archive assurance record in
`.runtime/archive-assurance.json` holds the publication baseline. A later
snapshot is a new operational cycle, not unfinished work from this one.

For a later production snapshot, refresh each platform safely: start with
discovery or `--dry-run`, run one source at a time, repair only extractors
affected by upstream changes, then parse and unify. Validate that produced
Parquets are not older than their raw/merged inputs. New DVC pushes remain
explicitly user-authorized.

### ChatGPT capture-delete cycle

**Status:** available as a manual operation; not an active development item.

The reconciler infrastructure, including the `preserved_missing` flag for
records removed from the server, is implemented and validated. When old
ChatGPT conversations are intentionally deleted on the server, the next
incremental capture should preserve them locally as `preserved_missing` while
the local raw copy remains intact.

Start with a small, deliberately chosen set of old conversations. Review the
result in `data/merged/ChatGPT/reconcile_log.jsonl` and in the processed
Parquet before repeating the exercise or applying it to another platform.

Automation is intentionally deferred: a script selecting conversations by age
could delete the wrong conversations server-side, and preservation locally
does not retain the ability to fetch a later server-side revision.

## Future platforms

None currently prioritized. The unified set covers 13 sources: the original
platform expansion through Grok and Kimi plus the later Antigravity CLI source.
