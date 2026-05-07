# Claude Code (CLI)

Source: `claude_code`. Mode: `cli`. Local data (not web capture) —
incremental copy from `~/.claude/projects/`.

## Why there is no `server-behavior.md`

The CLI has no server. "Rename/pin/delete" behavior does not apply the
same way — sessions are JSONL files in the user's filesystem.

**CLI equivalents:**
- "Delete on server" → user removes `<id>.jsonl` from `~/.claude/projects/`.
  `cli-copy.py` (line 11 of the docstring) preserves the already-copied
  file in `data/raw/Claude Code/`. Parser can mark
  `is_preserved_missing=True` by comparing raw vs current HOME.

## Schema specifics

- `interaction_type='ai_ai'` for subagents (sidechains) with
  `parent_session_id` pointing to the main session.
- **Compacted threads (`/compact`):** N JSONLs with the same internal
  sessionId become 1 Conversation with `conv_id=root`. See fix in
  `src/parsers/claude_code.py` (Phase 1: `_build_chain_links`).
- **Repeated events in raw JSONL:** defensive dedup by `uuid`.

## Parquets gerados

- `claude_code_conversations.parquet` — 1 linha por sessao
- `claude_code_messages.parquet` — msgs user/assistant
- `claude_code_tool_events.parquet` — tool calls/results
- `claude_code_branches.parquet` — 1 _main por sessao
- `claude_code_agent_memories.parquet` — parser le `<encoded-cwd>/memory/*.md` por projeto, materializa parquet com kind/name/description da frontmatter; preservation tracked via `home_memory_files` do `current_source_files("claude_code")`

## Where the real info lives

- **Parser:** `src/parsers/claude_code.py`
- **Copy script:** `src/extractors/cli/copy.py`
- **Quarto data profile:** `notebooks/claude-code.qmd`
- **Sync orchestrator:** `scripts/claude-code-sync.py`
