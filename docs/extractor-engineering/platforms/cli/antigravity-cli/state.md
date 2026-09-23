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
  `brain/<id>/.system_generated/logs/transcript_full.jsonl`, with fallback to
  `transcript.jsonl` when the complete representation is absent. Both contain
  JSONL records for user input, planner responses, thinking and tool activity,
  but the compact form can mark large fields as truncated.

The incremental copy takes a consistent SQLite backup for `.db` containers;
this safely incorporates an active WAL without copying credentials or general
configuration files. It also preserves the complete regular-file surface below
each `brain/<conversation>` directory, including generated documents and their
metadata sidecars, user uploads, readable trajectories, task logs and message
records. Finder metadata, embedded `.git/` trees and symlinks are excluded.
The readable trajectory, artifacts explicitly delivered through tool calls and
top-level documents carrying an Antigravity metadata sidecar are promoted to
the canonical schema. A sidecar document already represented byte-for-byte by
a tool-call artifact is deduplicated by content hash. The broader `brain/` copy
remains raw evidence for format comparison and future, evidence-backed
enrichment.

In the 2026-09-23 local census, the 13 conversations containing both forms had
identical row counts. The complete form restored differences in 413 of 927
records and removed all 91 observed `truncated_fields` markers, so it is the
preferred parser input. Files under `.system_generated/messages/` are internal
task/subagent messages, while `.system_generated/tasks/` contains operational
command and timer logs. They remain raw evidence: promoting them as user-facing
messages would duplicate part of the trajectory and promoting them as memory
would misclassify conversation-scoped execution state.

## Agent memory census

No durable agent-memory document was observed in the installed `agy 1.1.22`
state. `knowledge/` contains only an empty `knowledge.lock`; it does not prove
the existence of recoverable knowledge. Markdown under `brain/<conversation>`
contains plans, reports and snapshots produced inside a conversation, so it is
conversation output rather than cross-session memory. Those files must not be
published as `AgentMemory` without new format evidence. The census is
documented so a future version can be added deliberately if the storage
contract changes.

This differs from Claude Code's project-scoped `memory/*.md` and Codex's
global `memories/**/*.md`: both of those are durable cross-session memory
representations with immutable version manifests. Antigravity `brain/`
documents remain tied to one conversation. Comparisons should test recurrence,
cross-session reuse and provenance rather than infer memory from Markdown alone.

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

## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Antigravity CLI, the evidenced scope is the
assistant artifact linked as `output` to its exact `PLANNER_RESPONSE`; recovered
opaque history does not justify additional links. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).
