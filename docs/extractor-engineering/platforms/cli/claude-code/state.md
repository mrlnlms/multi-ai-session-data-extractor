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
  `src/platforms/claude_code/parser.py` (Phase 1: `_build_chain_links`).
- **Repeated events in raw JSONL:** defensive dedup by `uuid`.

## Preserved session assets

- **Inline user images:** JSONL `content[]` blocks of `type='image'` are the
  authoritative source. The parser verifies/materializes their base64 bytes in
  `data/raw/Claude Code/_images/`, publishes one user `Asset` and exact input
  `AssetLink` per block, and enriches `Message.asset_paths`. Identity combines
  the session/message/block locator with the content SHA-256. Existing bytes
  are reused only when their hash matches; the disposable
  `~/.claude/image-cache/` is not authoritative.

## Deferred enrichment
- **Operational metadata:** `message.usage`, `gitBranch`, `cwd`,
  `permissionMode` and attachment records are preserved in raw but are not
  first-class fields in the unified output. Promote them only with a concrete
  analysis need and a schema decision.

## Parquets gerados

- `claude_code_conversations.parquet` — 1 linha por sessao
- `claude_code_messages.parquet` — msgs user/assistant
- `claude_code_tool_events.parquet` — tool calls/results
- `claude_code_branches.parquet` — 1 _main por sessao
- `claude_code_agent_memories.parquet` — parser le `<encoded-cwd>/memory/*.md` por projeto, materializa parquet com kind/name/description da frontmatter; preservation tracked via `home_memory_files` do `current_source_files("claude_code")`
- `claude_code_assets.parquet` — imagens de entrada embutidas e preservadas
- `claude_code_asset_links.parquet` — relacao exata imagem → mensagem/bloco
- `_memory_metadata.json` no raw preserva o `mtime_ns` observado na fonte para
  que `created_at`/`updated_at` das memorias sejam reproduziveis apos um
  checkout DVC. Entradas de arquivos ausentes permanecem no sidecar junto do
  conteudo preservado.

## Asset vault transition

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit temporary rollback;
filesystem contents never select the mode. The legacy tree remains preserved,
while the vault reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Claude Code, reader scope is the inline
image block and its exact user-message position; deferred external path
enrichment is not inferred as an asset. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Where the real info lives

- **Parser:** `src/platforms/claude_code/parser.py`
- **Copy script:** `src/capture/cli/copy.py`
- **Quarto data profile:** `notebooks/claude-code.qmd`
- **Sync orchestrator:** `python -m src.platforms.claude_code.commands.sync`
