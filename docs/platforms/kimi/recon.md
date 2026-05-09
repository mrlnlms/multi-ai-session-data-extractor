# Kimi (Moonshot AI) — recon (probe 2026-05-09)

Probe via Claude in Chrome contra `kimi.com` (sessao logada via Google
OAuth).

## Auth

**Cookies sozinhos NAO bastam.** Endpoints retornam 401 sem
`Authorization: Bearer <access_token>`. Token vive em
**`localStorage.access_token`** (~563 chars, JWT-like). Existe tambem
`refresh_token` em localStorage.

Padrao headed login 1x → persistent context herda localStorage no profile.
Captura via `page.evaluate(localStorage.getItem('access_token'))` +
`Authorization: Bearer <token>` em cada request. Refresh do token: a
investigar (provavelmente endpoint que aceita `refresh_token`).

## URL pattern

- Home: `https://www.kimi.com/`
- Chat: `https://www.kimi.com/chat/<chat_id>` (UUID 36)

## API style

`POST /apiv2/<package>.<service>.<v>.<Service>/<Method>` — gRPC-Web /
Connect protocol style. Body JSON, response JSON. Existem tambem
endpoints REST `/api/...` (device register, user usage).

## Endpoints chave (probe 200 OK)

### Discovery / listagem

| Endpoint | Body | Response |
|---|---|---|
| `kimi.chat.v1.ChatService/ListChats` | `{pageSize: 100}` | 9 chats com files inline + nextPageToken |
| `kimi.gateway.skill.v1.SkillService/ListOfficialSkills` | `{}` | 46 skills oficiais |
| `kimi.gateway.skill.v1.SkillService/ListInstalledSkills` | `{}` | 5 skills instaladas (com pinned flag) |
| `kimi.gateway.claw.v1.ClawService/ListBots` | `{}` | empty (sem bots configurados) |
| `kimi.gateway.claw.v1.ClawService/ListWorkspaceBackups` | `{}` | claw workspace backups |
| `kimi.gateway.im.v1.IMService/ListRooms` | TBD | 400 com body vazio — payload requer mais campos |

### Conteudo de chat

| Endpoint | Body | Response |
|---|---|---|
| `kimi.chat.v1.ChatService/GetChat` | `{chatId}` | metadata + files + lastRequest options/tools/scenario |
| `kimi.chat.v1.ChatService/ListMessages` | `{chatId}` | 276KB no chat de 19 messages — DAG completo com blocks + refs |

### Auth / config

| Endpoint | Notas |
|---|---|
| `kimi.usersetting.v1.UserSettingService/GetUserSetting` | settings do usuario |
| `kimi.gateway.membership.v2.MembershipService/GetSubscription` | plan tier |
| `kimi.gateway.config.v1.ConfigService/GetConfig` | feature flags |
| `kimi.gateway.config.v1.ConfigService/GetAvailableModels` | modelos (K2.6 Instant etc) |
| `POST /api/device/register` | REST classico, registra device |
| `POST /api/user/usage` | quota |

### Auxiliares

- `kimi.gateway.suggest.v1.SuggestService/ListPopups`
- `kimi.gateway.order.v1.GoodsService/ListGoods`
- `POST /api/prompt-snippet/list`

## Schema da listagem `ListChats`

```
{
  chats: [{
    id (uuid),
    name (str),
    files: [{
      id, meta: {name, contentType, sizeBytes, checksum, ext, createTime, type},
      blob: {signUrl, previewUrl},
      tokenCount, status
    }],
    messageContent (preview, max 500 chars),
    createTime, updateTime
  }],
  nextPageToken (cursor)
}
```

Files vem inline na listagem com signed URLs — sem endpoint separado de
files-per-conv.

## Schema de `GetChat` (metadata)

```
chat: {
  id, name, files[],
  messageContent (preview),
  lastRequest: {
    options: {thinking: bool},
    tools: [{type}],     # ex: web_search
    scenario             # str(13) ex: "default_chat"
  },
  createTime, updateTime
}
```

## Schema de `ListMessages`

```
messages: [{
  id, parentId,           # DAG (branches via parentId — igual Qwen/Claude.ai)
  role,                   # 'user' | 'assistant' (probable; len str(9))
  status,                 # ex: 'completed'
  blocks: [{              # multiplos blocks por message
    id, parentId, messageId,
    text: {content},
    createTime
  }],
  refs: {
    searchChunks: [{      # search results disponiveis
      id, base: {title, url, siteName, iconUrl, snippet, publishTime}
    }],
    usedSearchChunks: [   # quais foram efetivamente citados
      ...same shape
    ]
  }
}]
```

## Sidebar features (UI)

- **Skills (modos especializados):** Slides, Websites, Docs, Deep
  Research, Sheets, Agent Swarm, Kimi Code, Kimi Claw (Beta).
  Equivalentes ao `mode`/`chat_type` de outras plataformas.
- **Chat History** com lista recente + "All Chats".
- **Kimi Claw** (Beta) — autonomous agent ("Kimi works 24/7"). Bots
  customizaveis via ClawService.

## URL patterns adicionais

- Profile pic / icons: `https://kimi-web-img.moonshot.cn/prod-data/icon-cache-img/<domain>` (cache de favicons de search results)
- Files signed URLs: TBD (provavelmente `*.moonshot.cn` similar)

## Mapeamento pro schema canonico

- `chat.id` → `Conversation.conversation_id`
- `chat.name` → `Conversation.title`
- `chat.lastRequest.scenario` → `Conversation.mode` (precisa mapping pra VALID_MODES)
- `chat.lastRequest.options.thinking` → settings_json
- `messages[].id` → `Message.message_id`
- `messages[].parentId` → branches (analogo Qwen)
- `messages[].role` → `Message.role`
- `blocks[*].text.content` concat → `Message.content`
- `refs.searchChunks` / `usedSearchChunks` → `ToolEvent` (event_type=search_call/_result)
- `chat.files[]` → assets per-conv (parser pode emitir asset metadata)

## Gaps conhecidos pre-implementacao

- Refresh do token: TBD — precisa probe se retorno 401 pra rodar
  refresh automatico via `refresh_token`.
- `IMService/ListRooms`: 400 com body vazio — payload obrigatorio TBD.
- Skills/categorias: ainda nao testado se aparecem em chats (campo
  `lastRequest.scenario`?). Probe quando capturar varios chats.
- Kimi Claw bots: vazio na conta atual — schema desconhecido sem dados.
- `media_posts` ou similar (entidade de "outputs publicaveis"): TBD se existe.
- Volume real: 9 chats listados na sidebar; "All Chats" pode revelar
  mais. Confirmar no full sync.

## TODO probe (pre-implementacao)

1. Tentar `pageSize=200` em `ListChats` pra confirmar paginacao via
   `nextPageToken`.
2. Mapear payload de `IMService/ListRooms` (rooms = ?).
3. Verificar `lastRequest.scenario` — quantos valores distintos
   aparecem nos 9 chats?
4. Endpoint de refresh do token.
5. URL pattern dos files (signed URLs vs CDN dedicado).
