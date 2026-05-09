# Grok — endpoints e schema (probe 2026-05-09)

Probe via Claude in Chrome contra grok.com (sessao logada).

## Auth

Cookies do dominio grok.com bastam — nenhum token em localStorage
necessario. Padrao: Playwright persistent context herda os cookies, e
fetch via `page.evaluate()` dentro do contexto envia cookies
automaticamente. Mesmo modelo do Qwen.

## URL pattern

- Home: `grok.com/`
- Chat solto: `grok.com/c/{conversationId}` (UUID)
- Project + chat: `grok.com/project/{workspaceId}?chat={conversationId}&rid={requestId}`
- `rid` na URL eh tracking client-side, nao precisa enviar pra API.

## Endpoints REST mapeados

Base: `https://grok.com`

### Listagem / discovery

| Endpoint | Method | Notas |
|---|---|---|
| `/rest/app-chat/conversations?pageSize=N` | GET | Lista todas (incluindo as em workspaces) |
| `/rest/app-chat/conversations?pageSize=N&pageToken={t}` | GET | Cursor pagination via `nextPageToken` |
| `/rest/app-chat/conversations?pageSize=N&filterIsStarred=true` | GET | Filtro starred |
| `/rest/app-chat/conversations?pageSize=N&workspaceId={id}` | GET | Filtra por workspace (project) |
| `/rest/app-chat/conversations?pageSize=1` | GET | Usado como count check |
| `/rest/workspaces?pageSize=N&orderBy=ORDER_BY_LAST_USE_TIME` | GET | Lista projects |
| `/rest/workspaces/shared?pageSize=N&orderBy=ORDER_BY_LAST_USE_TIME` | GET | Projects compartilhados |
| `/rest/workspaces/{workspaceId}` | GET | Detalhe completo do project |
| `/rest/assets?pageSize=N&orderBy=ORDER_BY_LAST_USE_TIME` | GET | Lista files (uploads + model-generated) |

Resposta da listagem de conv:

```json
{
  "conversations": [{
    "conversationId": "uuid",
    "title": "string",
    "starred": false,
    "createTime": "ISO 27 chars (com nanos)",
    "modifyTime": "ISO 24 chars (sem nanos)",
    "systemPromptName": "string (custom system prompt)",
    "temporary": false,
    "mediaTypes": [],
    "workspaces": [],
    "taskResult": {}
  }],
  "nextPageToken": "uuid (cursor)",
  "textSearchMatches": []
}
```

`temporary: true` = private chat (nao persiste? a confirmar).
`workspaces: [...]` populado quando conv esta dentro de project.
`taskResult` populado quando conv eh resultado de scheduled task.

### Conteudo de uma conv

| Endpoint | Method | Notas |
|---|---|---|
| `/rest/app-chat/conversations_v2/{convId}?includeWorkspaces=true&includeTaskResult=true` | GET | Metadata + workspace inline |
| `/rest/app-chat/conversations/{convId}/response-node?includeThreads=true` | GET | Tree skeleton (responseId + sender) |
| `/rest/app-chat/conversations/{convId}/load-responses` | POST | Body: `{"responseIds": [...]}` — retorna conteudo das messages |
| `/rest/app-chat/share_links?pageSize=100&conversationId={convId}` | GET | Share links da conv |
| `/rest/conversations/files/list?conversationId={convId}&path=%2F` | GET | Files anexados na conv |

### Schema de uma response (message)

Retornado por `load-responses`. Campos por response:

```
responseId       sender (user/assistant)   createTime    message
manual           partial                   shared        query / queryType
model            metadata                  steps         isControl
mediaTypes       streamErrors

# Conteudo extra
webSearchResults                citedWebSearchResults*
xpostIds  xposts  citedXposts
generatedImageUrls   imageEditUris   imageAttachments
fileAttachments      fileUris        fileAttachmentsMetadata*
cardAttachmentsJson  webpageUrls
toolResponses
ragResults  citedRagResults
searchedXSearchResults*  connectorSearchResults*  collectionSearchResults*
citedConnectorSearchResults*  citedCollectionSearchResults*

* nomes inferidos de prefixo/sufixo/length (filtro de privacidade do
  Claude in Chrome bloqueou os literais por parecerem base64). Parser
  vai armazenar response inteira como JSON raw, entao nao tem risco de
  perder campo nao mapeado.
```

### Schema de workspace (project)

```
workspaceId          name             createTime         lastUseTime
icon                 customPersonality (= instructions, truncated em 40 no detail)
preferredModel       isPublic          isReadonly         accessLevel
conversationStarters viewCount         conversationsCreatedCount
cloneCount
```

`customPersonality` parece ser o "Instructions" do project — confirmar
que nao truncado em endpoints reais (probe usou summary que limita len).

### Schema de asset (file global)

```
assetId          mimeType        name           sizeBytes
createTime       lastUseTime     summary        previewImageKey
key (storage path/url, ~87 chars)              auxKeys (dict)
isDeleted        fileSource      rootAssetId    isModelGenerated
isLatest         inlineStatus    isRootAssetCreatedByModel
sharedWithTeam   sharedWithUserIds   isPublic
```

## Endpoints gRPC-web (skip por enquanto)

Padrao `/prod.grok.connectors.manager.ConnectorManager/MethodName`.
Serializacao binaria. Connectors = integracoes externas (Drive, Gmail,
Notion). Nao critico pro extractor v1 — armazenamos referencia se vier
inline em responses (`connectorSearchResults`).

- `POST /prod.grok.connectors.manager.ConnectorManager/ListConnectorsV2`
- `POST /prod.grok.connectors.manager.ConnectorManager/ListAvailableConnectorsV2`
- `GET /api/oauth-connectors`

## Endpoints adicionais (relevancia menor)

- `GET /rest/user-settings` — `enableMemory`, `agentCustomizations`
- `POST /rest/system-prompt/list` — system prompts custom
- `GET /rest/tasks` — scheduled tasks (recurring queries)
- `GET /rest/tasks/inactive` — tasks pausadas
- `GET /rest/notifications/list?pageSize=N` — notificacoes
- `POST /rest/rate-limits` — quota check
- `GET /rest/products?provider=SUBSCRIPTION_PROVIDER_STRIPE` — planos
- `GET /rest/suggestions/profile` — sugestoes home

## Paginacao

`pageSize` + `nextPageToken` (cursor). Quando token volta vazio ou
`nextPageToken` ausente, fim.

## Headed vs headless

A confirmar empiricamente. SPA Next.js + Cloudflare — **comecar
headless**, cair pra headed se 403 / challenge "Just a moment...".
Pattern comum em ChatGPT/Perplexity exigiu headed; Qwen/DeepSeek/etc
funcionam headless.

## Gaps conhecidos

- **Imagine (image gen)**: paywall SuperGrok, nao captura. `generatedImageUrls` em responses pode ter assets mesmo no plano free? Probe quando aparecer caso real.
- **Private/temporary chats**: `temporary: true` flag — provavelmente nao listados por default, ou expirando. A confirmar.
- **Connectors data**: integracoes externas (Drive/Gmail). Skip — preservar so referencia em responses.
- **Tasks (scheduled)**: feature propria do Grok (recurring queries). Capturar metadata via `/rest/tasks` — opcional v1.

## Estrutura raw output (analoga ao Qwen)

```
data/raw/Grok/
├── LAST_CAPTURE.md
├── capture_log.json
├── capture_log.jsonl
├── discovery_ids.json
├── workspaces.json
├── conversations/{conv_id}.json   # contem: meta_v2 + response_node + responses + files + share_links
├── assets/{asset_id}.{ext}
├── assets_log.json
└── assets_manifest.json
```

Cada `{conv_id}.json` agrega multi-endpoint pra evitar refetch.
