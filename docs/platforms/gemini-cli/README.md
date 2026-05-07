# Gemini CLI

Source: `gemini_cli`. Mode: `cli`. Local data — incremental copy from
`~/.gemini/tmp/`.

## Schema specifics

- **JSON schema** (not JSONL like Claude Code/Codex): `session-<timestamp>-<sid>.json`
- **Periodic snapshots:** the same session can have N files with the
  same internal `sessionId`. Parser consolidates into 1 Conversation
  with dedup by `message_id`. See `src/parsers/gemini_cli.py:_parse_session`.
- `thoughts` array → formatted `thinking`.
- `toolCalls` correlated via status (`success`/`error`).
- **`logs.json` orphan handling:** convs presentes em `logs.json` sem
  `chats/session-*.json` correspondente viram Conversations com
  `is_preserved_missing=True` + Messages role=user (preservation policy).
  Sessions que existem em `chats/` sao ignoradas no `logs.json` — `chats/`
  eh a fonte canonica.

## Why there is no `server-behavior.md`

The CLI has no server. See `docs/platforms/claude-code/README.md` for
the "preservation at the raw level via cli-copy" pattern.

## Where the real info lives

- **Parser:** `src/parsers/gemini_cli.py`
- **Copy script:** `src/extractors/cli/copy.py`
- **Quarto data profile:** `notebooks/gemini-cli.qmd`
- **Sync orchestrator:** `scripts/gemini-cli-sync.py`
