# Gemini CLI

Source: `gemini_cli`. Mode: `cli`. Local data — incremental copy from
`~/.gemini/tmp/`.

The copy ignores new macOS `.DS_Store` metadata because it is neither session
content nor CLI state. A copy preserved before that exclusion remains in raw
as operational filesystem metadata and is not promoted to an Asset.

## Agent memory

Gemini CLI remains an active upstream project and calls its hierarchical
instructional context "memory". The collector preserves configured context
files (default `GEMINI.md`) from the global scope and from projects previously
observed through `tmp/*/.project_root`. It also recognizes the newer private
project `MEMORY.md` tier when present. These documents use the shared
versioned `AgentMemory` contract; general settings, credentials, skills and
pending auto-memory patches are not silently promoted to memory.

The current machine has preserved Gemini CLI sessions but no installed
`gemini` executable and no live memory Markdown. This is an observed local
state, not evidence that Gemini CLI was discontinued and not a reason to omit
future capture support.

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
- **Memory:** `agent_memories`, immutable `agent_memory_versions` and
  `agent_memory_temporal_evidence` follow the same timestamp-confidence
  contract as Claude Code and Codex.

## Why there is no `server-behavior.md`

The CLI has no server. See `docs/extractor-engineering/platforms/cli/claude-code/state.md` for
the "preservation at the raw level via cli-copy" pattern.

## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. Gemini CLI currently has no evidenced eligible
assets, so both readers preserve the empty canonical asset tables and do not
promote `ToolEvent.file_path` values. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Where the real info lives

- **Parser:** `src/platforms/gemini_cli/parser.py`
- **Copy script:** `src/capture/cli/copy.py`
- **Quarto data profile:** `notebooks/gemini-cli.qmd`
- **Sync orchestrator:** `python -m src.platforms.gemini_cli.commands.sync`
