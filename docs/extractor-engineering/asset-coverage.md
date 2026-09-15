# Canonical asset coverage

This is the archive-wide coverage contract for `assets.parquet` and
`asset_links.parquet`. The current scope is **partial preserved-file coverage**,
not `preserved_web_files`: all nine web sources now publish the graph, but
several preserved input, generated-output and project/notebook file
representations remain outside it until their identity and placement semantics
are validated.

Counts below describe the canonical archive materialized on 2026-09-15.
“Linked” is the percentage of source/account/asset identities with at least one
evidence-backed relationship; it is not a download-success rate. Available
paths are relative to `data/` and resolve to local files.

| Source | Assets / unique canonical IDs | Origin distribution | Links / role distribution | Linked | Available / missing | Reader capability | Excluded or deliberately separate representations |
|---|---:|---|---|---:|---:|---|---|
| ChatGPT | 997 / 997 | user 696; assistant 208; unknown 93 | 1,002; input 559, output 213, context 137, unknown 93 | 100.0% | 927 / 70 | inline | Project indexes, Canvas patches and account-memory exports remain operational/domain evidence rather than files delivered through an interaction |
| Claude.ai | 3,566 / 3,566 | user 2,082; assistant 1,484 | 3,617; input 1,892, output 1,484, context 241 | 100.0% | 3,292 / 274 | message | Extracted artifact versions are exact message outputs; inline text-bearing `attachments` and account-memory exports remain domain content rather than fake binaries |
| Gemini | 364 / 364 | assistant 173; user 110; unknown 81 | 963; input 787, output 176 | 78.0% | 364 / 0 | message | 27 additional physical copies (25 images and 2 reports) are verified same-account/content duplicates; no placement is invented for manifest-only images |
| NotebookLM | 4,712 / 4,712 | platform 4,499; assistant 213 | 4,712; context 4,499, output 213 | 100.0% | 4,712 / 0 | library | Text-only sources/outputs, missing downloads and expiring signed URLs stay in domain/raw evidence |
| Qwen | 367 / 367 | user 313; assistant 54 | 367; input 294, output 54, context 19 | 100.0% | 367 / 0 | inline | Rotated signed-URL manifest entries are consolidated; inline document text stays in domain tables |
| DeepSeek | 80 / 80 | user 80 | 80; input 80 | 100.0% | 0 / 80 | message | Native upload records remain metadata-only because no current binary or manifest survived in merged |
| Perplexity | 15 / 15 | assistant 9; user 6 | 8; input 8 | 40.0% | 9 / 6 | message | Third-party featured images are external references; deleted upstream uploads retain metadata only |
| Grok | 53 / 53 | user 53 | 0 | 0.0% | 53 / 0 | library | The global catalog has no evidence-backed use placement; none is inferred from names or timestamps |
| Kimi | 87 / 87 | unknown 87 | 87; unknown 87 | 100.0% | 86 / 1 | conversation | `chat.files[]` proves conversation membership, not author, direction, message or inline position |
| Claude Code | 3,443 / 3,443 | user 3,443 | 3,443; input 3,443 | 100.0% | 3,443 / 0 | inline | Inline base64 user images are verified against their materialized bytes; disposable home-directory caches are excluded |
| Codex | 44 / 44 | user 44 | 44; input 44 | 100.0% | 44 / 0 | inline | User-message data URIs are materialized; image payloads inside tool/guardian envelopes are not user-facing assets |
| Gemini CLI | 0 / 0 | — | 0 | — | 0 / 0 | library | Tool-output text spills and working-tree paths are operational evidence; no eligible session file is currently preserved |
| Antigravity CLI | 12 / 12 | assistant 12 | 12; output 12 | 100.0% | 12 / 0 | message | Explicit `ArtifactMetadata` + preserved `CodeContent` is eligible; opaque containers and ordinary tool paths are not assets |
| **Total** | **13,740 / 13,740** | user 6,827; assistant 2,153; platform 4,499; unknown 261 | **14,335**; input 7,107, output 2,152, context 4,896, unknown 180 | **98.9%** | **13,309 / 431** | mixed | Coverage expands only through source-specific evidence |

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

## Publication invariants

The unifier materializes composite-key uniqueness and rejects an asset graph
when an asset/link reference is unresolved; a non-null conversation, message,
project, source or output relationship does not resolve in the same
source/account namespace; an available path is unsafe or absent; a position is
negative; or any published asset-graph string exposes a recognized signed-query
credential.

The matrix is an observed snapshot. Source state documents remain authoritative
for extractor behavior and known limitations remain authoritative for gaps.
