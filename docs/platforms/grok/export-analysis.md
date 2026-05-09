# Grok — analise do export oficial (2026-05-09)

Snapshot: `data/external/grok-snapshots/2026-05-09/` (10MB extraido).

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

### Assets binarios — EXPORT RESOLVE GAP V1

Export tem **44 arquivos fisicos** em
`prod-mc-asset-server/<asset_id>/content` + 1 profile-picture.webp.

Extractor V1 so tinha metadata via `/rest/assets`. Implementar
asset_downloader via API exigiria gerar presigned URL a partir do
campo `key` (storage path 87 chars) — nao mapeado.

**Acao tomada:** copiados 45 binarios pra `data/raw/Grok/assets/<asset_id>.<ext>`
(com mime_type → extensao). Reconciler espelha pra
`data/merged/Grok/assets/`. Parser populates coluna
`asset_path` em `grok_assets.parquet` (relativo ao `data/`).

**Cobertura:** 44/44 metadata da API casaram com binarios do export
(todos `SELF_UPLOAD_FILE_SOURCE`, ambos os lados refletem mesmo estado).

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
| Asset binarios (44) | **Copiados pra `data/raw/Grok/assets/<id>.<ext>`** + parser populates `asset_path` |
| Profile picture | Copiada pra `data/raw/Grok/assets/<original-name>.webp` |

## Schedule de re-export

Grok export tem TTL de 30 dias (visivel no path `ttl/30d/`). Pra manter
binarios atualizados, re-export periodico necessario quando assets
novos forem uploaded — ou implementar asset_downloader via API
(deferred V2).
