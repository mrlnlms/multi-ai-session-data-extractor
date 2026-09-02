# Antigravity CLI

Source: `antigravity_cli`. Mode: `cli`. Local data from
`~/.gemini/antigravity-cli/`.

## Storage generations

- **Legacy:** `conversations/<id>.pb`. These containers are encrypted/opaque
  and are preserved raw. When there is no readable trajectory, the parser
  emits a zero-message Conversation stub instead of discarding it.
- **Current:** `conversations/<id>.db`, a SQLite database per conversation.
  Its payload columns are undocumented Protobuf blobs, so they are preserved
  as raw rather than parsed directly.
- **Canonical readable input:**
  `brain/<id>/.system_generated/logs/transcript.jsonl`. It contains JSONL
  records for user input, planner responses, thinking and tool activity.

The incremental copy takes a consistent SQLite backup for `.db` containers;
this safely incorporates an active WAL without copying credentials or general
configuration files.

## Recuperação manual de legados opacos

Esta não é uma etapa do sync. Em um caso pontual, quando o `agy` está aberto,
o daemon local dele pode devolver a trajetória já decriptada de um `.pb`. O
helper consulta somente `127.0.0.1`, não altera `~/.gemini/antigravity-cli` e
guarda o resultado em `data/raw/Antigravity CLI/recovered/`:

```bash
PYTHONPATH=. .venv/bin/python scripts/antigravity-recover-legacy.py --all-opaque
```

`recovery_manifest.jsonl` registra os SHA-256 do PB e da trajetória. Uma
recuperação bem-sucedida com o mesmo hash é ignorada nas execuções seguintes;
use `--force` somente para consultar novamente de propósito. Os sidecars
recuperados ficam preservados fora do parser regular até que exista uma
conversão de schema revisada para eles.

## Schema specifics

- `USER_INPUT` records become user Messages.
- `PLANNER_RESPONSE` records become assistant Messages; `thinking` and
  `tool_calls` are preserved.
- Tool steps such as `RUN_COMMAND`, `VIEW_FILE`, `CODE_ACTION`, searches and
  subagent invocation become ToolEvents.
- `history.jsonl`, `conversation_summaries.db` and cache metadata enrich title,
  workspace and summary when available; none is treated as authoritative for
  discovery because the indexes can lag behind the physical conversations.

## Parquets generated

- `antigravity_cli_conversations.parquet`
- `antigravity_cli_messages.parquet`
- `antigravity_cli_tool_events.parquet`
- `antigravity_cli_branches.parquet`

## Where the real info lives

- **Parser:** `src/parsers/antigravity_cli.py`
- **Copy script:** `src/extractors/cli/copy.py`
- **Sync orchestrator:** `scripts/antigravity-cli-sync.py`
- **Quarto data profile:** `notebooks/antigravity-cli.qmd`
