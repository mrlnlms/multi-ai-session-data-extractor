# Kimi (Moonshot AI) — technical coverage

## Pipeline

- **Single cumulative folder:** `data/raw/Kimi/` and `data/merged/Kimi/`.
- **Sync orchestrator (3 steps):** `scripts/kimi-sync.py` (capture +
  assets + reconcile).
- **Headless capture** (Cloudflare did not block on smoke 2026-05-09).
- **Auth:** persistent profile in `.storage/kimi-profile-<account>/`
  (generated via `scripts/kimi-login.py`). Cookies + Bearer token from
  `localStorage.access_token` (~563 chars JWT-like). Cookies-only = 401.
  Token loaded via `page.evaluate(localStorage.getItem)` em cada captura.

## Coverage

Conversations + skills (oficiais + instaladas) + assets binaries via
signUrl inline. Reconciler V1 (FEATURES_VERSION=1): full preservation
for convs + assets cumulativos.

### Reference volume (smoke 2026-05-09)

- 9 chats / 5 skills instaladas / 46 oficiais.
- 261 messages (130 assistant / 122 user / 9 system) / 70k words.
- 82 tool_events: 49 fetch_urls_call + 30 web_search_call + 3 ipython_call.
- 26 asset binaries (3.76MB) baixados via signUrl.

## Canonical parser

`src/parsers/kimi.py`.

### Coverage

- **Role mapping:** `user`/`assistant`/`system` → canonical roles.
- **Status:** `MESSAGE_STATUS_COMPLETED` (default) / `MESSAGE_STATUS_UNSPECIFIED`.
- **Scenario:** `SCENARIO_K2D5` (K2.6 Instant default) → mode `chat`.
  Outros scenarios (Slides/Docs/Deep Research/Sheets/Agent Swarm/Kimi
  Code/Kimi Claw) ainda nao apareceram empiricamente — mapping a
  enriquecer.
- **Block kinds:** `text` (concat em `content`), `tool` (1 ToolEvent
  por block, com `args` em `command` e `contents` em `result`),
  `file` (attachment_names + asset_path).
- **Files inline em `chat.files[]`:** signUrl (TTL) → download direto
  via fetch sem auth (URLs pre-assinadas Moonshot CDN). Salvos em
  `data/raw/Kimi/assets/<chat_id>/<file_id>.<ext>` (mime → ext) com
  manifest em `assets_manifest.json`.
- **Branches:** parser monta DAG via `parentId` mas V1 emite **1 branch
  por conv** (sem fork detection). `childrenMessageIds` mapeado mas
  nao usado pra split — refinar V2 quando observarmos forks reais.
- **Skills:** 5 instaladas viram rows em `kimi_project_metadata.parquet`
  (analogo a Qwen project; description vai pra `custom_instruction`).
- **Refs (search chunks):** quando msg tem `refs.usedSearchChunks` MAS
  nao tem `block.tool` (caso raro), emite ToolEvent pra preservar.
  Caso comum: block.tool ja captura — refs é duplicacao/agregacao.

### Not covered V1

- **Branches multiplas:** DAG mapeado mas sem split por
  `childrenMessageIds`. V1 = 1 branch por conv. Refinar quando
  observarmos forks empiricamente.
- **Scenario mapping:** so `SCENARIO_K2D5` na conta atual. Adicionar
  mapping pra outros scenarios (research/search/etc) quando aparecerem.
- **Refresh do token:** se `access_token` expirar, captura quebra.
  Implementar refresh via `refresh_token` em V2.
- **Kimi Claw bots:** `ListBots` retornou vazio. Schema desconhecido
  ate user criar bots.
- **`IMService/ListRooms`:** 400 com body vazio — payload obrigatorio TBD.
- **Block.file schema completo:** smoke nao mostrou block.file populado
  com dado rico (attachments vieram em `chat.files[]` inline). Probe V2.

## Descriptive Quarto

`notebooks/kimi.qmd`. Primary color `#3DB39E` (Moonshot teal-green).

## Validated CRUD scenarios

V1 smoke only ran capture against organic conv state. Empirical CRUD
matrix to be filled when destructive ops are tested:

| Scenario | Result |
|---|---|
| Rename | TBD |
| Delete | TBD |
| Skill switch | TBD |

## API endpoints (probe 2026-05-09)

Detalhes em [recon.md](recon.md).

Endpoints chave:

- `POST /apiv2/kimi.chat.v1.ChatService/ListChats` body `{pageSize, pageToken?}`
- `POST /apiv2/kimi.chat.v1.ChatService/GetChat` body `{chatId}`
- `POST /apiv2/kimi.chat.v1.ChatService/ListMessages` body `{chatId}`
- `POST /apiv2/kimi.gateway.skill.v1.SkillService/ListOfficialSkills`
- `POST /apiv2/kimi.gateway.skill.v1.SkillService/ListInstalledSkills`

Cursor pagination via `nextPageToken`. Bearer token obrigatorio em
`Authorization: Bearer <localStorage.access_token>`.
