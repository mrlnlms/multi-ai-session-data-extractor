# Gemini CLI

Source: `gemini_cli`. Mode: `cli`. Local data — incremental copy from
`~/.gemini/tmp/`.

The copy ignores new macOS `.DS_Store` metadata because it is neither session
content nor CLI state. A copy preserved before that exclusion remains in raw
as operational filesystem metadata and is not promoted to an Asset.

## Schema specifics

- **JSON schema** (not JSONL like Claude Code/Codex): `session-<timestamp>-<sid>.json`
- **Periodic snapshots:** the same session can have N files with the
  same internal `sessionId`. Parser consolidates into 1 Conversation
  with dedup by `message_id`. See `src/platforms/gemini_cli/parser.py:_parse_session`.
- `thoughts` array → formatted `thinking`.
- `toolCalls` correlated via status (`success`/`error`).
- **`logs.json` orphan handling:** convs presentes em `logs.json` sem
  `chats/session-*.json` correspondente viram Conversations com
  `is_preserved_missing=True` + Messages role=user (preservation policy).
  Sessions que existem em `chats/` sao ignoradas no `logs.json` — `chats/`
  eh a fonte canonica.
- **Assets de sessao:** nenhuma representacao elegivel foi observada no acervo
  atual. `tool-outputs/**/*.txt` sao spills operacionais de resultados de
  ferramentas; `write_file`/`replace` operam arquivos do working tree e ficam
  como `ToolEvent.file_path`, sem transformar paths externos em assets. O
  parser publica tabelas `assets`/`asset_links` vazias com schema canonico.

## Why there is no `server-behavior.md`

The CLI has no server. See `docs/extractor-engineering/platforms/cli/claude-code/state.md` for
the "preservation at the raw level via cli-copy" pattern.

## Asset vault transition

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved, while redundant byte copies now live only in the vault,
while the vault reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. Gemini CLI currently has no evidenced eligible
assets, so both readers preserve the empty canonical asset tables and do not
promote `ToolEvent.file_path` values. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Where the real info lives

- **Parser:** `src/platforms/gemini_cli/parser.py`
- **Copy script:** `src/capture/cli/copy.py`
- **Quarto data profile:** `notebooks/gemini-cli.qmd`
- **Sync orchestrator:** `python -m src.platforms.gemini_cli.commands.sync`
