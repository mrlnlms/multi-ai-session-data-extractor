# Kimi (Moonshot AI) — technical coverage

## Pipeline

- **Per-account cumulative folders:** every durable raw/merged tree uses
  `account-<account_id>/`. The local profile key is resolved from the UUID
  binding; selective sync uses `python -m src.workflows.account_sync
  <account_id> --apply`.
- **Sync orchestrator (3 steps):** `python -m src.platforms.kimi.commands.sync` (capture +
  assets + reconcile).
- **Headless capture** (Cloudflare did not block on smoke 2026-05-09).
- **Auth:** persistent profile in `.storage/kimi-profile-<account>/`
  (generated via `python -m src.platforms.kimi.commands.login`). Cookies + Bearer token from
  `localStorage.access_token` (~563 chars JWT-like). Cookies-only = 401.
  Token loaded via `page.evaluate(localStorage.getItem)` em cada captura.
  If the first API call returns 401, the client reloads the already logged-in
  site session, reloads the token, and retries once; a persistent 401 remains
  a hard failure. Chrome provider login is not required.
  Since 2026-08-30, the login and runtime origin is `https://kimi.ai/`
  (Google SSO remains supported).

### Latest validated collection — 2026-08-30

- On `kimi.ai`, incremental discovery listed 51 chats, 50 official skills, and
  4 installed skills. Forty new chat bodies were fetched and 11 reused, with
  zero fetch errors.
- Reconciliation added 40 chats and copied 11 (51 total), with no current
  server-missing records.
- The isolated asset pass downloaded 51 files, reused 28 existing files, and
  recorded 1 unavailable URL without affecting conversations.
- The canonical parser produced 51 conversations, 1,288 messages, 226 tool
  events, 51 branches, and 4 installed skills; unified parquets were
  regenerated.

### Additional account validation — 2026-09-12

- An isolated `account-2` profile captured 5 chats,
  1 installed skill, and 5 binary files with zero fetch or asset errors.
- The combined parser produced 56 conversations, 1,389 messages, 249 tool
  events, 56 branches, and 5 installed skills.

### Latest validated collection — 2026-09-20

- Both observable profiles were validated explicitly. The default profile
  rediscovered and reused all 53 chats; `account-2` grew from 5 to 6 chats,
  fetched the new body without error, and downloaded 3 new binary files.
  Repeated runs then reused all 53 and 6 chats respectively.
- The combined parser produced 59 conversations, 1,514 messages, 249 tool
  events, 59 branches, 2 installed skills, and 90 assets. Eighty-nine assets
  are locally available; the remaining signed URL is the previously known
  unavailable upstream object.
- The run exposed the same preservation boundary previously observed in Qwen:
  vault mode refreshed the manifest but skipped the then-required compatibility
  projection into merged. The immediate parity fix preserved that projection
  in both reader modes. The subsequent vault-only correction stopped
  rematerializing it during normal capture, and the retention audit removed the
  prior byte copy only after proving it in the vault. The archive-wide
  coverage audit returned to zero gaps; vault verification, unify, all 6
  selected Quarto reports, and the complete test suite pass.
- The collector requires an authenticated `kimi.ai` session and access token.
  During this run, the `account-2` token expired again shortly after two
  successful incremental reads, so a freshly completed login is not proof of
  durable future authentication. General browser-profile identity guidance is
  documented in `docs/SETUP.md` rather than as a Kimi-specific requirement.

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.sync
PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.login --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.parse
```

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

Each account tree resolves its immutable catalog UUID into `account_id`; the
legacy `account` label and all existing native IDs remain unchanged.

`src/platforms/kimi/parser.py`.

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
  via fetch sem auth (URLs pre-assinadas Moonshot CDN). O layout
  `data/raw/Kimi/assets/<chat_id>/<file_id>.<ext>` e staging ou compatibilidade
  legacy; no fluxo `vault` normal, o blob verificado fica em `data/assets` e o
  staging e retirado. `assets_manifest.json` permanece como evidencia, e o
  reconciler nao rematerializa a arvore binaria em `merged` no modo vault.
  Caminhos publicados sao relativos a `data/`. A URL assinada permanece apenas
  no manifest sob DVC e nunca entra no Parquet processado. O catalogo canonico
  mantem esses arquivos com `asset_origin=unknown`, pois `chat.files[]` nao
  prova autoria. `kimi_asset_links.parquet` registra a associacao observavel a
  conversa com `role=unknown`; mensagem, posicao inline e direcao nao sao
  inferidas.
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
- **Kimi Claw bots:** `ListBots` retornou vazio. Schema desconhecido
  ate user criar bots.
- **`IMService/ListRooms`:** 400 com body vazio — payload obrigatorio TBD.
- **Block.file schema completo:** smoke nao mostrou block.file populado
  com dado rico (attachments vieram em `chat.files[]` inline). Probe V2.
- **Binario indisponivel:** registros do manifest continuam em
  `kimi_assets.parquet` com `asset_path` nulo e
  `is_binary_available=False`; disponibilidade local e diferente de
  `preserved_missing` upstream.

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

Detalhes em [discovery.md](discovery.md).

Endpoints chave:

- `POST /apiv2/kimi.chat.v1.ChatService/ListChats` body `{pageSize, pageToken?}`
- `POST /apiv2/kimi.chat.v1.ChatService/GetChat` body `{chatId}`
- `POST /apiv2/kimi.chat.v1.ChatService/ListMessages` body `{chatId}`
- `POST /apiv2/kimi.gateway.skill.v1.SkillService/ListOfficialSkills`
- `POST /apiv2/kimi.gateway.skill.v1.SkillService/ListInstalledSkills`

Cursor pagination via `nextPageToken`. Bearer token obrigatorio em
`Authorization: Bearer <localStorage.access_token>`.

O comportamento da migracao de origem e outros fatos upstream ficam em
[server-behavior.md](server-behavior.md).
## Asset vault contract

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit compatibility and
diagnostic mode; filesystem contents never select the mode. Legacy records and
manifests remain preserved. Redundant byte copies now live only in the vault,
whose reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. For Kimi, reader scope preserves the observable
conversation/file association; unknown author or message placement remains
unknown rather than being inferred. See the [operational
transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Explicit login-health check

A one-row `ListChats` request is the established read-only check; cookies plus the existing `access_token` are required. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
