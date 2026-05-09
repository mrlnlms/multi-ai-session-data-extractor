# Grok — technical coverage

## Pipeline

- **Single cumulative folder:** `data/raw/Grok/` and `data/merged/Grok/`.
- **Sync orchestrator (2 steps):** `scripts/grok-sync.py` (capture +
  reconcile).
- **Headless capture** (Cloudflare did not block on smoke 2026-05-09).
- **Auth:** persistent profile in `.storage/grok-profile-<account>/`
  (generated via `scripts/grok-login.py`). Login via grok.com (SSO da
  conta X). Cookies bastam — sem token em localStorage.

## Coverage

Conversations + workspaces (projects) + workspace conv cross-ref.
Reconciler V1 (FEATURES_VERSION=1): full preservation for convs +
workspaces.

### Reference volume (smoke 2026-05-09)

- 6 convs / 1 workspace / 1 conv-in-workspace.
- 156 messages (78 user / 78 assistant) / 62 tool_events.
- 44 assets (37 PNG, 4 PDF, 2 DOCX, 1 JPG; 10MB total, all uploads).
- 0 scheduled tasks (active + inactive).

## Canonical parser

`src/parsers/grok.py`.

### Coverage

- **Sender mapping:** `human → user`, `assistant`/`ASSISTANT → assistant`
  (case-insensitive).
- **Models:** `grok-3`, `grok-4`, `grok-4-auto` (last-assistant wins).
- **ToolEvent emit** when array has items, per category:
  - `web_search` / `cited_web_search` (from `webSearchResults` /
    `citedWebSearchResults`)
  - `xposts` / `cited_xposts`
  - `rag` / `cited_rag`
  - `connector_search` / `cited_connector_search`
  - `collection_search` / `cited_collection_search`
  - `product_search` (from `searchProductResults`)
  - `image_gen` (from `generatedImageUrls`)
  - `tool_response` (from `toolResponses`)
- **`starred` → `is_pinned`** (cross-platform).
- **`temporary` → `is_temporary`** (private chats).
- **Workspace metadata** with `customPersonality` (instructions),
  `preferredModel`, `viewCount`, `cloneCount` etc -> `project_metadata`
  parquet (canonical name aligned with Qwen/Claude.ai).
- **Cross-ref conversation->workspace** via
  `grok_conversation_projects.parquet` (canonical mapping table).

### Files (assets) — global per user

`/rest/assets` retorna uploads do user + arquivos gerados pelo modelo.
Capturados em `data/raw/Grok/assets.json` (cumulativo via reconciler com
preservation por `assetId`). Parser emite `grok_assets.parquet`
(asset_id, mime_type, name, size_bytes, key, file_source,
is_model_generated, is_latest, is_deleted, etc).

Acesso na UI: avatar (canto inferior esquerdo) -> Files
(`grok.com/files`).

### Tasks (scheduled queries) — shell pronto

`/rest/tasks` + `/rest/tasks/inactive` retornam scheduled prompts
recorrentes (active + inactive + usage quotas). Schema preliminar
salvo em `tasks.json`; parser emite `grok_scheduled_tasks.parquet`
quando ha pelo menos 1 task. Smoke 2026-05-09: 0 tasks na conta —
schema sera enriquecido empiricamente quando aparecerem.

Acesso na UI: avatar -> Tasks (`grok.com/tasks`).

### Not covered V1

- **Branches:** `response_node.threads` (when `includeThreads=true`)
  may surface alternative paths in long convs. Smoke samples were
  linear — V1 ignores threads, all messages in `<conv_id>_main` branch.
- **Asset binarios:** so metadata capturado. Download via `key` (storage
  path 87 chars) deferred — analogo a chatgpt asset_downloader.
- **Imagine (image generation):** paywall (SuperGrok). `generatedImageUrls`
  may surface free-tier renders if available — captured via ToolEvent
  but no asset download yet.
- **Connectors content:** Drive/Gmail/Notion integrations referenced
  in `connectorSearchResults` are external — only metadata preserved.

## Descriptive Quarto

`notebooks/grok.qmd`: ~40MB HTML (depends on volume). Primary color
`#1DA1F2` (X / xAI blue).

## Validated CRUD scenarios

V1 smoke only ran capture against organic conv state. Empirical CRUD
matrix to be filled when destructive ops are tested:

| Scenario | Result |
|---|---|
| Rename | TBD |
| Star (pin) | TBD |
| Move to workspace | TBD — `_workspace_ids` cross-ref handles |
| Delete | TBD |
| Temporary chat | TBD — `temporary` flag captured |

## API endpoints (probe 2026-05-09)

Detalhes em [recon.md](recon.md) — mantido como ref de schema.

Endpoints chave:

- `GET /rest/app-chat/conversations?pageSize=N[&pageToken][&workspaceId]`
- `GET /rest/app-chat/conversations_v2/{cid}?includeWorkspaces=true&includeTaskResult=true`
- `GET /rest/app-chat/conversations/{cid}/response-node?includeThreads=true`
- `POST /rest/app-chat/conversations/{cid}/load-responses`
  body `{"responseIds": [...]}`
- `GET /rest/workspaces?pageSize=N&orderBy=ORDER_BY_LAST_USE_TIME`
- `GET /rest/workspaces/{wid}` — detail with `customPersonality`

Cursor pagination via `nextPageToken`. Cookies-only auth.
