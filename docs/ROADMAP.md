# Roadmap

This is the operational index for outstanding work and important completed
decisions. It intentionally links to the evidence and technical detail rather
than duplicating it here. Shipped work belongs in `git log`; platform-specific
behavior belongs in its own documentation.

**Last reviewed:** 2026-08-31.

## Current operational state

| Item | Status | Evidence | Next safe action |
|---|---|---|---|
| Reconciliation recovery | Complete (2026-08-29) | [RECOVERY.md](RECOVERY.md) | Treat the promoted tree as canonical. |
| DVC Google Drive remote | In sync, rechecked 2026-08-30 | [AGENTS.md](../AGENTS.md) and [RECOVERY.md](RECOVERY.md) | Run `.venv/bin/dvc status -c -r gdrive_remote` before a material new collection or storage operation. |
| Capture and processing | Unblocked | [AGENTS.md](../AGENTS.md) | Run the normal sync → parse → unify pipeline when updating a source. |
| DVC garbage collection | Prohibited during the transition | [AGENTS.md](../AGENTS.md) | Do not run `dvc gc`. |

The Google Drive remote is transitional. Every new `dvc push` still requires
explicit user authorization.

## Product evolution reading map

This is the short index for humans and agents working on the archive product.
Read only the documents required by the question at hand; platform-specific
behavior remains in each platform's own documentation.

| Question | Authoritative document | Role |
|---|---|---|
| What product is this becoming, and what remains deliberately open? | [PERSONAL_AI_ARCHIVE.md](PERSONAL_AI_ARCHIVE.md) | Product vision; not a spec. |
| What is the current priority and what work is operationally pending? | This roadmap | Ordering and status. |
| How should IDs, references and non-message events be interpreted? | [data-identity-and-reader-fidelity.md](data-identity-and-reader-fidelity.md) | Technical record for the reader and future curation. |
| What is the canonical capture and processing contract? | [AGENTS.md](../AGENTS.md) and [`src/schema/models.py`](../src/schema/models.py) | Agent instructions and observable schema. |
| What does a particular source currently capture or miss? | [`platforms/`](platforms/) and [LIMITATIONS.md](LIMITATIONS.md) | Per-source evidence and known gaps. |
| How is the existing dashboard operated? | [dashboard/manual.md](dashboard/manual.md) | Current operational UI. |
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

The intended recovery contract is:

```text
Git repository (code + .dvc pointers) + one verified DVC object remote
    = recreate the project data at the matching Git revision with dvc pull
```

Browser profiles and cookies in `.storage/` are deliberately outside that
contract and require a new login after a clean-machine restore. A clean restore
must be demonstrated before retiring any previous remote.

The target is a **single** object-storage remote, not a permanent Drive + R2
arrangement. Drive remains only during a future migration and validation.

### Storage design work

| Work item | Status | Intended outcome |
|---|---|---|
| Evaluate a single DVC object remote | Planned | Remove DVC objects from personal Google Drive without reducing the archive merely to fit an arbitrary free tier. |
| Oracle Object Storage proof of concept | Candidate, not approved | Test a private S3-compatible Oracle bucket. Its published Always Free allocation is 20 GB and 50,000 Object Storage API calls/month; DVC's real request count must be measured before choosing it. |
| Asset vault design | Planned after storage decision | Store each downloaded binary once; raw and merged records refer to it through a manifest with content hash and provenance. |
| Retention audit for `data/external/` | Planned | Classify each set as active input, unique recovery evidence, or verified duplicate before any storage-policy change. |

References: [Oracle Always Free Object Storage](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
[Oracle S3 Compatibility API](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/s3compatibleapi.htm), and
[DVC S3-compatible remotes](https://doc.dvc.org/user-guide/data-management/remote-storage/amazon-s3).

#### Proposed storage sequence

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

#### Asset vault target model

This is a logical DVC-managed layer, not a database of BLOBs and not a second
cloud provider:

```text
data/raw/<source>/       original structured capture + asset references
data/assets/<source>/    one canonical local copy per binary content hash
data/merged/<source>/    reconciled records + the same asset references
asset manifest           source, record/output IDs, MIME, size, hash, name,
                         capture time and canonical asset path
```

`data/assets/` would be DVC-tracked and stored in the same selected object
remote. The refactor must preserve byte-level hashes, be idempotent, and prove
that parser and restore behavior remain correct. It improves local checkout,
asset discovery and future growth; DVC already deduplicates byte-identical
assets between `raw` and `merged`, so it is not expected to magically remove
all current remote storage.

### Archive reader product

**Status:** next product exploration. It does not need to wait for the storage
remote or asset-vault decisions.

The reader is currently the clearest product gap: collection and analytical
access exist, but the preserved messages themselves cannot be inspected
comfortably. It also becomes a feedback surface for finding capture, parser,
schema and presentation gaps that remain invisible in aggregate dashboards.

Build a local-first, read-only interface distinct from the operational
Streamlit dashboard:

- conversation list, source filters and search in a sidebar;
- selected conversation rendered as a chat timeline;
- branches, citations and tool events shown as contextual details;
- assets rendered from current references and, later, through the asset
  manifest; and
- source-specific metadata available without exposing the personal archive to
  a public backend.

The first design should start from the existing unified Parquets and preserve a
path to rich media through the future asset manifest. CLI timelines need
explicit treatment for thinking, tool calls/results, trajectory steps and
events without canonical messages. The relevant identity and fidelity findings
are recorded in
[data-identity-and-reader-fidelity.md](data-identity-and-reader-fidelity.md).

### Product fronts and current emphasis

This is an order for product exploration, not a requirement to finish one
front completely before touching another:

| Front | Current emphasis | Why |
|---|---|---|
| Archive and reader | First | Closes the immediate visibility gap and reveals fidelity issues in real conversations. |
| Operation and health | Second | Evolves the existing Streamlit capabilities for accounts, logins, runs and diagnostics. |
| Assisted curation | Third and iterative | Depends on reading context and on durable references, while reusing work from `AI Interaction Analysis`. |

Parser and schema refinements should be made incrementally when the reader
provides concrete evidence. A full anticipatory rewrite of all sources is not a
prerequisite.

## Decisions requiring explicit direction

| Decision | Why it is not automatic | Evidence | First step once chosen |
|---|---|---|---|
| Choose the single DVC object remote | It changes storage provider, cost, request limits and the recovery contract. R2 is paid above 10 GB; Oracle is a candidate but needs a request-count proof of concept. | [data-storage-inventory.md](data-storage-inventory.md) and [storage design work](#storage-design-work) | Approve a non-destructive Oracle proof of concept, or choose another provider. |
| Change the unified schema or publish changed unified data | The consumer project must coordinate on schema changes. | [AGENTS.md](../AGENTS.md) | Agree the contract with `AI Interaction Analysis` before publishing. |
| Automate deletion of conversations upstream | A selection bug could irreversibly delete the wrong server-side conversations. | [ChatGPT capture-delete cycle](#chatgpt-capture-delete-cycle) | Keep this manual unless a future need justifies automation. |

## Operational work

### Reactivation and compatibility cycle

**Status:** planned.

Before a new production snapshot, refresh each platform safely: start with
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

## Coverage backlog

These are feature edges and validation opportunities, not blockers for the
current pipeline. Their source documents are authoritative and should be
updated when the item is investigated or closed.

| Area | Examples of open coverage | Authoritative source |
|---|---|---|
| Perplexity Max / Pro features | Computer mode, scheduled tasks, model council, modern Deep Research. | [LIMITATIONS.md](LIMITATIONS.md#perplexity) |
| Gemini | Draft/regenerate alternatives; additional account support; branches, grounding citations and Add to notebook. | [LIMITATIONS.md](LIMITATIONS.md#gemini) and [Gemini server behavior](platforms/gemini/server-behavior.md) |
| DeepSeek | Agent mode, full R1 reasoning sample and uploaded files. | [DeepSeek server behavior](platforms/deepseek/server-behavior.md) |
| NotebookLM | Map a representative real chat when one exists upstream. | [LIMITATIONS.md](LIMITATIONS.md#notebooklm) |
| Cross-platform test depth | HTTP/auth/Playwright integration tests are empirical today; mocked coverage is a possible v1.0 investment. | [LIMITATIONS.md](LIMITATIONS.md#test-coverage) |

## Future platforms

None currently prioritized. The unified set covers 13 sources: the original
platform expansion through Grok and Kimi plus the later Antigravity CLI source.
