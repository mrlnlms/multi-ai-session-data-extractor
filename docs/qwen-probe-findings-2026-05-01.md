# Qwen — probe findings 2026-05-01

Probe via `qwen-export.py --smoke 5` + inspecao do raw. Profile reusado de
`~/Desktop/AI Interaction Analysis/.storage/qwen-profile-default/` (34M).

## Endpoints (todos OK em 2026-05-01)

| Endpoint | Funcao | Status |
|---|---|---|
| `GET /api/v2/chats/?page=N` | Lista chats fora de project | ✅ |
| `GET /api/v2/chats/?page=N&project_id=X` | Lista chats em project | ✅ |
| `GET /api/v2/chats/pinned` | Pinados | ✅ |
| `GET /api/v2/chats/{id}` | Fetch individual | ✅ |
| `GET /api/v2/projects/` | Lista projects | ✅ |
| `GET /api/v2/projects/{id}/files` | Files em project | ✅ |

Headers ainda funcionam: `source=web, bx-v=2.5.36`. Auth via Bearer
do `localStorage.token`.

## Volume capturado

- **115 chats** discovered
- **3 projects** (Teste IA Interaction, Qualia, Travel) — 4 project files
- **0 pinned**, **0 archived** nesta base (mas schema tem os campos)

## chat_type distribution (**8 tipos!**)

| chat_type | Count | Notas |
|---|---|---|
| `t2t` | 75 | text-to-text default |
| `search` | 19 | web search dedicado |
| `deep_research` | 12 | **Deep Research proprio** (espelho do ChatGPT) |
| `t2i` | 3 | text-to-image |
| `t2v` | 1 | text-to-video |
| `artifacts` | 1 | artifacts mode (codigo/canvas) |
| `learn` | 1 | learn mode (educational) |
| `null` | 3 | legacy (anteriores ao schema atual?) |

**Implicacao:** parser legacy assume tudo como chat texto puro — perde
artifacts, deep research, image/video gen, search results, learn-specific.

## Schema raw — top-level (`data`)

```python
{
    "id": str,                    # UUID
    "title": str,
    "chat_type": str,             # t2t / search / deep_research / t2i / t2v / artifacts / learn
    "pinned": bool,
    "archived": bool,             # ja no schema (0 vistos nesta base)
    "project_id": str | null,
    "folder_id": str | null,      # **folders feature** — verificar comportamento
    "share_id": str | null,       # **sharing** — links publicos
    "currentId": str,             # message_id da branch ativa (leaf)
    "currentResponseIds": list,   # leafs alternativos (branches!)
    "user_id": str,
    "created_at": str,            # epoch como STRING (atencao!)
    "updated_at": str,
    "models": list | null,        # modelos usados na conv
    "meta": {
        "timestamp": int,
        "tags": list[str]         # **tags** customizadas pelo user
    },
    "chat": {                     # estrutura interna
        "history": {
            "messages": dict,     # keyed por msg id
        },
        "messages": list,         # array linear (talvez redundante c/ history)
        "models": list
    }
}
```

## Schema raw — message

```python
{
    "id": str,
    "parentId": str | null,        # **branches** (DAG plano)
    "childrenIds": list[str],      # **branches**
    "role": str,                   # 'user' | 'assistant'
    "content": str,
    "content_list": list[dict],    # blocks com timestamps (parsear pra latencia)
    "reasoning_content": str | "", # **Qwen reasoning** (R1-equivalente, condicional ao modelo)
    "model": str,
    "modelIdx": int,
    "modelName": str,
    "chat_type": str,
    "sub_chat_type": str,          # 't2t' visto, outros possiveis
    "info": dict | null,           # **search_results** moram aqui
    "meta": dict,
    "timestamp": int,
    "turn_id": int | null,
    "feature_config": dict,
    "extra": dict,
    "annotation": dict | null,     # citations / referencias
    "feedbackId": str | null,
    "done": bool,
    "edited": bool,
    "is_stop": bool,
    "error": str | null
}
```

## Project schema

```python
{
    "id": str,
    "name": str,
    "icon": str,                  # emoji ou similar
    "custom_instruction": str,    # equivalente ao prompt_template do Claude.ai
    "memory_span": int | null,    # retention (?) — investigar
    "created_at": int,
    "updated_at": int,
    "_files": list                # injetado pelo extractor — files do project
}
```

3 projects observados (1 do user pra teste: "Teste IA Interaction" com 1 chat
type='learn'; outros 2 reais: Qualia + Travel).

## Gaps do parser legacy (`src/parsers/qwen.py`, 114 linhas)

| Feature | Schema raw | Legacy parser |
|---|---|---|
| `chat_type` | ✅ | ❌ ignora — todos viram mode='chat' |
| `pinned` | ✅ | ❌ |
| `archived` | ✅ | ❌ |
| `project_id` | ✅ | ❌ |
| `folder_id` | ✅ | ❌ |
| `share_id` | ✅ | ❌ |
| `currentId` (branches leaf) | ✅ | ❌ — caminha so via childrenIds[-1] |
| `parentId` / `childrenIds` (DAG) | ✅ | parcial — segue ultimo child |
| `reasoning_content` | ✅ | ❌ |
| `info` (search_results) | ✅ | ❌ |
| `meta.tags` | ✅ | ❌ |
| `content_list` timestamps | ✅ | parcial — pega so o primeiro |
| Project `custom_instruction` | ✅ | ❌ — projects sem parser |
| Project `_files` | ✅ | ❌ |

## Plano parser v3 Qwen

1. **Schema canonico** — usar campos que ja temos do Claude.ai +
   `mode` mapeado por `chat_type` (search/research/dalle/etc do enum)
2. **Branches** via `currentId` + `parentId`/`childrenIds` (mesmo algoritmo
   do Claude.ai, ja existe em `_claude_ai_helpers.build_branches`)
3. **reasoning_content** → `Message.thinking`
4. **info.search_results** → `ToolEvent` (event_type=`search_call/_result`)
5. **content_list timestamps** → `Message.start_timestamp` / `stop_timestamp`
6. **meta.tags** → `Conversation.settings_json` ou nova coluna
7. **share_id, folder_id** → Conversation novos campos? ou settings_json
8. **Project com custom_instruction + files** → `project_metadata` table +
   reuso de `project_docs` table criada pra Claude.ai

## Pasta unica + pasta de raw

Atual: `data/raw/Qwen Data/<YYYY-MM-DDTHH-MM>/` (legacy timestamp)
Alvo: `data/raw/Qwen/` (pasta unica) — espelhar Claude.ai/Perplexity

## Chats fixture pra validacao

User criou project "Teste IA Interaction" (id=d8b46ac7) com 1 chat
(e217fd39, "Discussão sobre Fontes", chat_type='learn') especificamente
pra exercitar parsing de projects/learn. Vai como fixture.

Outros chat_types unicos pra fixtures: `artifacts` (980a5719), `t2v`
(o unico), `t2i` (3 — Network Graph Designs / Diagrama / Infographic).

## TODOs durante implementacao — STATUS

- [x] **Endpoint `/api/v2/chats/{id}/messages`:** mensagens vem inline em
  `data.chat.history.messages` (dict keyed por id) — sem paginacao adicional.
- [x] **`is_stop`:** confirmado, msgs com `is_stop=true` viram
  `finish_reason='user_stop'`.
- [x] **`feature_config` por msg:** preservado em `Conversation.settings_json`
  (extraido do primeiro msg user) — contem flags como `web_search`,
  `image_gen`, etc.
- [x] **Folders:** schema tem `folder_id` mas 0 valores nesta base. Parser
  preserva na settings_json. Behavior runtime depende da UI — nao bloqueia.
- [x] **Sharing:** schema tem `share_id` mas 0 valores. Parser ignora —
  recriar sob demanda quando user usar feature.
- [x] **Asset download:** 326 URLs detectadas, 321 baixadas (5 erros
  por URL expirada). 196MB local. Parser resolve via `assets_manifest.json`:
  171 msgs com `asset_paths` populados.
- [x] **CRUD historico via parent snapshots:** validado em
  `docs/qwen-server-behavior.md` (4 snapshots, +6 added, 0 deletes/renames).
