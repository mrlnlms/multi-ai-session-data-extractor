# Canonical asset coverage

This is the archive-wide coverage contract for `assets.parquet` and
`asset_links.parquet`. The current scope is **partial preserved-file coverage**,
not `preserved_web_files`: eight of nine web sources publish the graph, and
several preserved representations remain outside it until their identity and
placement semantics are validated.

Counts below describe the canonical archive materialized on 2026-09-14.
“Linked” is the percentage of source/account/asset identities with at least one
evidence-backed relationship; it is not a download-success rate. Available
paths are relative to `data/` and resolve to local files.

| Source | Assets / unique canonical IDs | Origin distribution | Links / role distribution | Linked | Available / missing | Reader capability | Excluded or deliberately separate representations |
|---|---:|---|---|---:|---:|---|---|
| ChatGPT | 684 / 684 | user 559; assistant 125 | 689; input 559, output 130 | 100.0% | 614 / 70 | inline | Project sources, canvas and deep-research representations without validated native file evidence |
| Claude.ai | 2,449 / 2,449 | user 2,082; assistant 367 | 2,500; input 1,892, output 367, context 241 | 100.0% | 2,175 / 274 | message | Inline text-bearing `attachments` and extracted artifacts are message/domain content, not fake binaries |
| Gemini | 364 / 364 | assistant 173; user 110; unknown 81 | 963; input 787, output 176 | 78.0% | 364 / 0 | message | No placement is invented for manifest-only images; repeated signed-URL representations are not published |
| NotebookLM | 4,712 / 4,712 | platform 4,499; assistant 213 | 4,712; context 4,499, output 213 | 100.0% | 4,712 / 0 | library | Text-only sources/outputs, missing downloads and expiring signed URLs stay in domain/raw evidence |
| Qwen | 367 / 367 | user 313; assistant 54 | 367; input 294, output 54, context 19 | 100.0% | 367 / 0 | inline | Rotated signed-URL manifest entries are consolidated; inline document text stays in domain tables |
| DeepSeek | 0 / 0 | — | 0 | — | 0 / 0 | library | Preserved file/image representations have no validated canonical asset adapter yet |
| Perplexity | 15 / 15 | assistant 9; user 6 | 8; input 8 | 40.0% | 9 / 6 | message | Third-party featured images are external references; deleted upstream uploads retain metadata only |
| Grok | 53 / 53 | user 53 | 0 | 0.0% | 53 / 0 | library | The global catalog has no evidence-backed use placement; none is inferred from names or timestamps |
| Kimi | 87 / 87 | unknown 87 | 87; unknown 87 | 100.0% | 86 / 1 | conversation | `chat.files[]` proves conversation membership, not author, direction, message or inline position |
| Claude Code | 0 / 0 | — | 0 | — | 0 / 0 | library | Inline base64 image blocks and disposable image caches are not first-class canonical assets |
| Codex | 0 / 0 | — | 0 | — | 0 / 0 | library | No validated preserved-file adapter |
| Gemini CLI | 0 / 0 | — | 0 | — | 0 / 0 | library | No validated preserved-file adapter |
| Antigravity CLI | 0 / 0 | — | 0 | — | 0 / 0 | library | Opaque containers remain raw evidence; no validated preserved-file adapter |
| **Total** | **8,731 / 8,731** | user 3,123; assistant 941; platform 4,499; unknown 168 | **9,326**; input 3,540, output 940, context 4,759, unknown 87 | **98.4%** | **8,380 / 351** | mixed | Coverage expands only through source-specific evidence |

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
