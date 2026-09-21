# Antigravity CLI

Source: `antigravity_cli`. Mode: `cli`. Local data from
`~/.gemini/antigravity-cli/`.

## Storage generations

- **Legacy:** `conversations/<id>.pb`. These containers are encrypted/opaque
  and are preserved raw. A decoded `recovered/<id>.trajectory.json` sidecar,
  when available, is converted into the canonical schema; otherwise the
  parser emits a zero-message Conversation stub instead of discarding it.
- **Current:** `conversations/<id>.db`, a SQLite database per conversation.
  Its payload columns are undocumented Protobuf blobs, so they are preserved
  as raw rather than parsed directly.
- **Canonical readable input:**
  `brain/<id>/.system_generated/logs/transcript.jsonl`. It contains JSONL
  records for user input, planner responses, thinking and tool activity.

The incremental copy takes a consistent SQLite backup for `.db` containers;
this safely incorporates an active WAL without copying credentials or general
configuration files.

## Recuperação de legados opacos

Esta é uma ferramenta excepcional da plataforma, não uma etapa automática do
sync. Quando o `agy` está aberto, o daemon local pode devolver a trajetória já
decriptada de um `.pb`. O comando consulta somente `127.0.0.1`, não altera
`~/.gemini/antigravity-cli` e guarda o resultado em
`data/raw/Antigravity CLI/recovered/`:

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.antigravity_cli.commands.recover_legacy --all-opaque
```

`recovery_manifest.jsonl` registra os SHA-256 do PB e da trajetória. Uma
recuperação bem-sucedida com o mesmo hash é ignorada nas execuções seguintes;
use `--force` somente para consultar novamente de propósito. O parser normal
consome os sidecars automaticamente. A prioridade é transcript atual,
trajetória legacy recuperada e, por último, stub opaco.

## Schema specifics

- `USER_INPUT` records become user Messages.
- `PLANNER_RESPONSE` records become assistant Messages; `thinking` and
  `tool_calls` are preserved.
- Tool steps such as `RUN_COMMAND`, `VIEW_FILE`, `CODE_ACTION`, searches and
  subagent invocation become ToolEvents.
- `history.jsonl`, `conversation_summaries.db` and cache metadata enrich title,
  workspace and summary when available; none is treated as authoritative for
  discovery because the indexes can lag behind the physical conversations.
- Recovered legacy steps use the same canonical records as current
  trajectories and set `capture_method='legacy_antigravity_daemon'`.
- Escritas com `ArtifactMetadata` e `CodeContent` constituem artefatos
  explicitamente entregues. O parser materializa o conteudo preservado em
  `data/raw/Antigravity CLI/_artifacts/`, valida SHA-256 e publica um Asset de
  origem assistant com AssetLink `output` para a `PLANNER_RESPONSE` exata.
  `TargetFile` sem esse marcador continua apenas como caminho operado por tool.

## Parquets generated

- `antigravity_cli_conversations.parquet`
- `antigravity_cli_messages.parquet`
- `antigravity_cli_tool_events.parquet`
- `antigravity_cli_branches.parquet`
- `antigravity_cli_assets.parquet`
- `antigravity_cli_asset_links.parquet`

## Where the real info lives

- **Parser:** `src/platforms/antigravity_cli/parser.py`
- **Copy script:** `src/capture/cli/copy.py`
- **Legacy recovery:** `src/platforms/antigravity_cli/legacy_recovery.py`
- **Sync orchestrator:** `python -m src.platforms.antigravity_cli.commands.sync`
- **Quarto data profile:** `notebooks/antigravity-cli.qmd`

## Asset vault transition

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved, while redundant byte copies now live only in the vault,
while the vault reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Antigravity CLI, the evidenced scope is the
assistant artifact linked as `output` to its exact `PLANNER_RESPONSE`; recovered
opaque history does not justify additional links. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).
