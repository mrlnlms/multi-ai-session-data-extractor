# Roadmap

Open work items. Closed via shipped releases are removed from this list
(see `git log` for history). For broader context, see
[README.md](../README.md) and [CLAUDE.md](../CLAUDE.md).

## Capture & parse — features

### Claude Code image extraction

Claude Code stores user-attached images **inline as base64** in JSONL
session files (`content[].source.data` in `type=image` blocks). The
parser currently does not handle `type=image` — only `text`, `tool_use`,
`tool_result`, and `thinking`. Sample scan: ~445 image blocks in 5
sessions, extrapolating to thousands across the corpus.

**Plan:** in `src/parsers/claude_code.py`, in the content-block loop,
detect `type == "image"`, decode base64, infer extension from
`source.media_type` (`image/jpeg` → `.jpg`), save to
`data/raw/Claude Code Data/_images/{session_id}/{msg_seq}_{block_idx}.{ext}`,
register the path in `attachment_names` of the `Message`. Other Claude
Code fields currently dropped: `message.usage` (token counts),
`gitBranch`, `cwd`, `permissionMode`. Details in
[docs/research/extractor-findings.md](research/extractor-findings.md).

### Claude.ai memories

Claude.ai exposes a "Memory" feature in the UI (preferences/instructions
the assistant remembers across sessions). The current extractor does not
capture it — `src/extractors/claude_ai/api_client.py` has zero references
to memory/preferences endpoints. Compare with ChatGPT, which already
saves `chatgpt_memories.md` as part of every capture.

**Plan:**
1. Probe the Claude.ai API to find the endpoint that returns memories
   (likely under `/api/organizations/{org_id}/...`).
2. Add it to `ClaudeAPIClient` and persist as `claude_ai_memories.md`
   (or similar) in the raw output, mirroring ChatGPT's pattern.
3. Decide whether memories enter the canonical schema as a new auxiliary
   table or stay as a standalone artifact.

## Operational

### ChatGPT capture-delete cycle

The reconciler infrastructure (with `preserved_missing` flag for items
removed from the server) is in place and validated. Operational next
step: gradually delete old conversations on the server. The next
incremental capture (`--since last`) should surface deleted IDs as
`preserved_missing` while keeping the local raw intact. Replicable to
other platforms once their reconcilers are equally validated.

This is mostly a manual operational task — kept here as a reference
point when reviewing chat details and deciding what to remove from the
server. Automation is feasible (script that lists conversations older
than N days without recent updates and calls the delete endpoint) but
risky: a bug in the selection logic deletes the wrong conversations
server-side, and although the reconciler preserves the local copy, you
lose the ability to re-fetch updated versions from the server. Start
manual; consider automation only after confidence is high.
