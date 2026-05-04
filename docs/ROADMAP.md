# Roadmap

Open work items, by category. Items closed via shipped releases are removed
from this list (see `git log` for history). For the broader project context
and current state, see [README.md](../README.md) and [CLAUDE.md](../CLAUDE.md).

## Capture & parse — features

### Claude Code image extraction

Claude Code stores user-attached images **inline as base64** in JSONL
session files (`content[].source.data` in `type=image` blocks). The parser
currently does not handle `type=image` — it only processes `text`,
`tool_use`, `tool_result`, and `thinking`. Sample scan: ~445 image blocks
in 5 sessions, extrapolating to thousands across all sessions.

**Plan:** in `src/parsers/claude_code.py`, in the content-block loop,
detect `type == "image"`, decode base64, infer extension from
`source.media_type` (`image/jpeg` → `.jpg`), save to
`data/raw/Claude Code Data/_images/{session_id}/{msg_seq}_{block_idx}.{ext}`,
register the path in `attachment_names` of the `Message`. Other Claude
Code fields currently dropped: `message.usage` (token counts),
`gitBranch`, `cwd`, `permissionMode`. Details in
[docs/research/extractor-findings.md](research/extractor-findings.md).

### Claude.ai memories

`memories.json` exposed by Claude.ai (settings/memory feature) is not yet
captured nor present in the canonical schema. Decide: ingest into a new
auxiliary table, or treat as conversation-attached metadata. No current
parser/extractor reference to memories.

### URL-targeted ingestion

Single-conversation ingestion: given a chat URL
(`claude.ai/chat/uuid`, `chatgpt.com/c/uuid`), open Playwright, capture
that conversation, feed the pipeline. Useful for ad-hoc captures outside
the periodic sync. Currently the only path is full sync.

## Operational

### CLI capture automation

`cli-copy.py` runs manually before each pipeline. Possible automation
paths: (1) Claude Code session-start hook, (2) cron daily, (3)
macOS launchd plist. Without automation, gaps appear in the timeline
(historical observation: 14-day gap in Apr/2026 with ~3.8k live sessions
vs ~4k copied).

### ChatGPT capture-delete cycle

The reconciler infrastructure (with `preserved_missing` flag for items
removed from the server) is in place and validated. Operational next
step: gradual delete of old conversations on the server. The next
incremental capture (`--since last`) should surface deleted IDs as
`preserved_missing` while keeping the local raw intact. Replicable to
other platforms once their reconcilers are equally validated.

### Voice DOM pass decision

`src/extractors/chatgpt/dom_voice.py::capture_voice_dom` is now
redundant — `audio_transcription` arrives in the API response (see
[extractor-findings.md](research/extractor-findings.md)). Decide:
remove the dead code path, or keep as a theoretical fallback for cases
where the API stops returning transcripts. `detect_voice_candidates`
(heuristic) remains useful regardless.

## Refinement

### Data versioning beyond DVC

Current state: DVC versions the full vault (raw + merged + processed +
unified + external). Beyond that, no per-record ingestion timestamp and
no git tag per run. Possible additions: timestamp column in
`Message`/`Conversation` (when this row entered the unified set), git
tags per pipeline run for reproducibility, or surfacing
`_last_seen_in_server` more prominently. Driven by the question: "when
did this specific conversation enter our local archive?"
