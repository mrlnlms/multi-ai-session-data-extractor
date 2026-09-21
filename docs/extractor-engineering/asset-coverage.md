# Canonical asset coverage

This is the archive-wide coverage contract for `assets.parquet` and
`asset_links.parquet`. The nine-source web scope is published as
**`preserved_web_files`**: every eligible file representation evidenced by the
raw/merged records, manifests and audited historical copies for all nine web
sources is represented by a canonical Asset, while every other observed
representation is matched by an approved, auditable exclusion rule. The
four-source CLI scope is independently published as
**`preserved_cli_session_assets`** under the same evidence requirement; it is
not inferred merely from a path appearing in a ToolEvent or from a zero-row
source.

Counts below describe the canonical archive materialized on 2026-09-15.
“Linked” is the percentage of source/account/asset identities with at least one
evidence-backed relationship; it is not a download-success rate. Available
paths are relative to `data/` and resolve to local files.

| Source | Assets / unique canonical IDs | Origin distribution | Links / role distribution | Linked | Available / missing | Reader capability | Excluded or deliberately separate representations |
|---|---:|---|---|---:|---:|---|---|
| ChatGPT | 1,117 / 1,117 | user 696; assistant 328; unknown 93 | 1,122; input 559, output 333, context 137, unknown 93 | 100.0% | 1,047 / 70 | inline | 149 reconstructed Canvas states are outputs; their operation records remain domain evidence, and account-memory exports remain outside the Asset domain |
| Claude.ai | 3,566 / 3,566 | user 2,082; assistant 1,484 | 3,617; input 1,892, output 1,484, context 241 | 100.0% | 3,292 / 274 | message | Extracted artifact versions are exact message outputs; inline text-bearing `attachments` and account-memory exports remain domain content rather than fake binaries |
| Gemini | 364 / 364 | assistant 173; user 110; unknown 81 | 963; input 787, output 176 | 78.0% | 364 / 0 | message | 27 historical duplicate representations were byte-proven before their redundant copies were retired; no placement is invented for manifest-only images |
| NotebookLM | 5,252 / 5,252 | platform 4,499; assistant 740; user 13 | 5,252; context 4,512, output 740 | 100.0% | 5,252 / 0 | library | 179 real note Markdown files, 105 mind-map trees and 250 text-output envelopes retain exact note/output identity; 184 legacy UUID-reference/empty Markdown materializations are operational, not notes |
| Qwen | 367 / 367 | user 313; assistant 54 | 367; input 294, output 54, context 19 | 100.0% | 367 / 0 | inline | Collision-safe filenames and recapture resolved all 11 historical upload-path collisions; 207 historical duplicate representations were byte-proven before their redundant copies were retired |
| DeepSeek | 80 / 80 | user 80 | 80; input 80 | 100.0% | 0 / 80 | message | Native upload records remain metadata-only because no current binary or manifest survived in merged |
| Perplexity | 15 / 15 | assistant 9; user 6 | 8; input 8 | 40.0% | 9 / 6 | message | Nine older artifact paths match canonical native identity and content; third-party featured images are external references and deleted upstream uploads retain metadata only |
| Grok | 53 / 53 | user 53 | 0 | 0.0% | 53 / 0 | library | The global catalog has no evidence-backed use placement; none is inferred from names or timestamps |
| Kimi | 87 / 87 | unknown 87 | 87; unknown 87 | 100.0% | 86 / 1 | conversation | `chat.files[]` proves conversation membership, not author, direction, message or inline position |
| Claude Code | 3,443 / 3,443 | user 3,443 | 3,443; input 3,443 | 100.0% | 3,443 / 0 | inline | Inline base64 user images are verified against their materialized bytes; disposable home-directory caches are excluded |
| Codex | 44 / 44 | user 44 | 44; input 44 | 100.0% | 44 / 0 | inline | User-message data URIs are materialized; image payloads inside tool/guardian envelopes are not user-facing assets |
| Gemini CLI | 0 / 0 | — | 0 | — | 0 / 0 | library | Tool-output text spills and working-tree paths are operational evidence; no eligible session file is currently preserved |
| Antigravity CLI | 12 / 12 | assistant 12 | 12; output 12 | 100.0% | 12 / 0 | message | Explicit `ArtifactMetadata` + preserved `CodeContent` is eligible; opaque containers and ordinary tool paths are not assets |
| **Total** | **14,400 / 14,400** | user 6,840; assistant 2,800; platform 4,499; unknown 261 | **14,995**; input 7,107, output 2,799, context 4,909, unknown 180 | **98.8%** | **13,969 / 431** | mixed | Coverage expands only through source-specific evidence |

## Reader capability levels

- `inline`: at least some links carry an exact message content-block position.
- `message`: links resolve to a message, but exact inline placement is absent or
  not reliable for the whole source.
- `conversation`: evidence proves conversation membership only.
- `library`: assets are browsable as a catalog or through a specialized domain
  object; conversational placement is absent or the adapter is not implemented.

These labels describe the strongest supported reading mode, not completeness.
For example, Gemini also has unlinked library rows, and NotebookLM links files
to authoritative source/output objects rather than chat messages.

NotebookLM's text-bearing materializations are first-class preserved
representations of user-facing objects even though the pipeline writes the
local serialization. Type-1 notes are user context, type-2 saved chat answers
are assistant outputs. All 179 actual current-tree note Markdown files, 105
mind-map trees and 250 text-output envelopes are covered. The other 184 legacy
files in the note directory contain only an internal UUID reference (183) or no
useful body (1), so they are explicitly inventoried as an old materializer
defect rather than mislabeled as historical notes. Six historical generated
briefs are covered from the immutable external archive. The note and output
domain tables remain authoritative; Asset metadata does not duplicate their
content.

ChatGPT Canvas request/response records are replayed along the preserved
conversation graph. The current archive yields 149 immutable file states: 37
creates with complete content and 112 successful update states, including 21
states recovered by joining the canonical raw with the immutable legacy
flattened snapshot on conversation identity and exact message timestamp. Each
state links to its producing request message. The 117 legacy patch JSON files
remain reproducible operation evidence rather than duplicate Assets.

## Publication invariants

The unifier materializes composite-key uniqueness and rejects an asset graph
when an asset/link reference is unresolved; a non-null conversation, message,
project, source or output relationship does not resolve in the same
source/account namespace; an available path is unsafe or absent; a position is
negative; or any published asset-graph string exposes a recognized signed-query
credential.

The stricter archive-wide pre-publication gate is:

```bash
PYTHONPATH=. .venv/bin/python -m src.operations.asset_coverage_audit --check
```

It prints independent web and CLI blocks and exits nonzero for uncovered or
unresolved evidence, ambiguous policy matches, available paths that do not
resolve, dangling AssetLinks, non-unique eligible identities or incomplete
accounting. Both the nine-source web block and four-source CLI block are green.
Filesystem metadata such as a previously preserved `.DS_Store` is inventoried
as operational evidence rather than silently removed or promoted to an Asset;
new CLI copies ignore that replaceable metadata.
These independent gates are the publication evidence for
`preserved_web_files` and `preserved_cli_session_assets`, respectively.

The matrix is an observed snapshot. Source state documents remain authoritative
for extractor behavior and known limitations remain authoritative for gaps.
