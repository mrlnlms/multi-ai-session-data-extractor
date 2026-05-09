# Grok — analise do export oficial (2026-05-09)

Snapshot: `data/external/grok-snapshots/2026-05-09/` (10MB extraido).

> **Atualizacao 2026-05-09 (pos-asset_downloader):** asset binarios
> agora vem da API via `https://assets.grok.com/<key>` (44/44
> bit-identical ao export — sha256 + size). Export passa a ser **so
> blob historico** preservado pra recovery; pipeline canonico nao
> depende dele.

## Pacotes do export

```
ttl/30d/export_data/<user_id>/
├── prod-grok-backend.json       (3MB) — convs/projects/tasks/media_posts
├── prod-mc-auth-mgmt-api.json   (2.7KB) — profile + sessions
├── prod-mc-billing.json         (18B) — {"balance_map":{}}
└── prod-mc-asset-server/
    ├── <asset_id>/content       × 44 — binarios fisicos
    └── <user_id>-profile-picture.webp
```

## Comparacao com extractor V1

### Convs metadata

Export (21 campos) vs API (10 campos via `conversations_v2.conversation`):

| Campo | Export | API V1 | Util? |
|---|---|---|---|
| `id` / `conversationId` | ✓ | ✓ | igual |
| `title` | ✓ | ✓ | igual |
| `create_time` / `createTime` | ✓ | ✓ | igual |
| `modify_time` / `modifyTime` | ✓ | ✓ | igual |
| `starred` | ✓ | ✓ | igual |
| `temporary` | ✓ | ✓ | igual |
| `system_prompt_name` | ✓ | ✓ | igual |
| `media_types` | ✓ | ✓ | igual |
| `summary` | so export | so API se `includeSummary` (probe nao testou) | **vazio na conta atual (0/6)** |
| `asset_ids` | so export | so API via cross-ref | **vazio na conta atual** |
| `leaf_response_id` | so export | nao | util pra branches futuro (deferred) |
| `system_prompt_id` (vs name) | so export | so name | marginal |
| `task_result_id` | so export | so via `taskResult` inline | marginal |
| `x_user_id` | so export | nao | marginal |
| `controller` | so export | nao | marginal |
| `team_id` | so export | nao | marginal (free tier sem team) |
| `shared_with_team` | so export | nao | marginal |
| `shared_with_user_ids` | so export | nao | marginal |
| `root_asset_id` | so export | nao | marginal |

**Veredicto convs:** export so adiciona campos marginais ou vazios. Nao
vale criar parser separado.

### Responses (mensagens) — extractor SUPERIOR

Export retorna **7 campos** por response (`_id`, `conversation_id`,
`message`, `sender`, `create_time`, `metadata`, `model`).

API (via `load-responses`) retorna **36 campos** incluindo:
- `webSearchResults`, `citedWebSearchResults`
- `xpostIds`, `xposts`, `citedXposts`
- `ragResults`, `citedRagResults`
- `connectorSearchResults`, `citedConnectorSearchResults`
- `collectionSearchResults`, `citedCollectionSearchResults`
- `searchProductResults`
- `generatedImageUrls`, `imageEditUris`, `imageAttachments`
- `fileAttachments`, `fileUris`, `fileAttachmentsMetadata`
- `cardAttachmentsJson`
- `toolResponses`, `steps`
- `metadata` (rico)
- `manual`, `partial`, `shared`, `isControl`
- `query`, `queryType`
- `webpageUrls`, `streamErrors`

**Veredicto:** extractor V1 captura tool events / search / RAG /
xposts / image gen — export oficial nao tem nada disso. **Nao usar
export pra responses.**

### Assets binarios — fechado via API (export agora redundante)

Export tem **44 arquivos fisicos** em
`prod-mc-asset-server/<asset_id>/content` + 1 profile-picture.webp.

**Probe 2026-05-09 (pos-export-analysis):** descobri via inspecao do
DOM que existe CDN dedicado `assets.grok.com`. URL determinístico:
`https://assets.grok.com/<key>` onde `key` e o campo retornado pela
listagem `/rest/assets` (formato `users/<uid>/<aid>/content`). Auth
funciona via cookies do mesmo eTLD+1.

`src/extractors/grok/asset_downloader.py` implementa download via
`page.evaluate(fetch + base64)`. Sync agora roda 3 etapas:
capture + assets + reconcile.

**Validacao:** 44 binarios baixados via API → sha256 + size
bit-identical aos do export (10.02MB total em ambos). API e export
referenciam o mesmo storage backend.

**Resultado:** export deixa de ser usado pelo pipeline. `data/external/
grok-snapshots/` permanece preservado **so como blob historico** pra
recovery extremo (caso conta seja deletada e binarios sumam).

### Sessions/auth — preservado como blob

`prod-mc-auth-mgmt-api.json` tem profile + 3 sessions com:
- `sessionId`, `createTime`, `expirationTime`, `status`
- `cfMetadata` (Cloudflare): IP, city, country, region, lat/long, timezone
- `userAgent` (Mozilla/Chrome, GrokApp/55 CFNetwork iOS)
- `signInMethod` (GOOGLE_OAUTH2)

Sem schema cross-platform pra sessions ainda — preservado como blob
em `data/external/grok-snapshots/<date>/`. Util pra:
- Auditoria de acesso
- Geo-localizacao de uso
- Cross-ref iOS app vs web

### Billing

`{"balance_map":{}}` — vazio (free tier). Estrutura existe pra quando
houver creditos.

### `media_posts` e `tasks`

Ambos vazios na conta atual. `media_posts` parece ser entidade nova
(posts publicados via Grok no X?) — schema desconhecido sem dados.

## Decisao final

| Item do export | Acao |
|---|---|
| `prod-grok-backend.json` | Preservado em `data/external/`, **nao parsado** (extractor V1 superior) |
| `prod-mc-auth-mgmt-api.json` | Preservado como blob (sessions interessantes, sem parser) |
| `prod-mc-billing.json` | Preservado (vazio mas estrutura) |
| Asset binarios (44) | ~~Copiados~~ **Baixados via API** (`assets.grok.com/<key>`); export redundante |
| Profile picture | Preservada no snapshot; nao integrada ao raw (nao listada em `/rest/assets`) |

## Schedule de re-export

**Nao necessario pro pipeline canonico.** asset_downloader via API
mantem `data/raw/Grok/assets/` atualizado a cada `grok-sync.py` —
asset novo aparece em `/rest/assets`, downloader pega.

Re-export so faz sentido se quiser refrescar os blobs preservados
em `data/external/grok-snapshots/`. TTL de 30 dias no servidor
(visivel no path `ttl/30d/`) eh do storage do export-tool, nao
afeta o storage real dos assets (que vive em `assets.grok.com`
indefinidamente enquanto a conta existir).
