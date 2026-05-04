# DeepSeek — probe findings 2026-05-01

Probe via `deepseek-export.py --smoke 5` + inspecao do raw. Profile reusado
de `~/Desktop/AI Interaction Analysis/.storage/deepseek-profile-default/` (23M).

## Endpoints (todos OK em 2026-05-01)

| Endpoint | Funcao | Status |
|---|---|---|
| `GET /api/v0/chat_session/fetch_page?lte_cursor.pinned=false&...` | Lista sessions (cursor-paginated) | ✅ |
| `GET /api/v0/chat_session/fetch_page?lte_cursor.pinned=true` | Pinned sessions | ✅ |
| `GET /api/v0/chat/history_messages?chat_session_id=X` | Fetch individual | ✅ |

Headers: `x-app-version=20241129.1, x-client-version=1.8.0` ainda funcionam.
Auth via Bearer do `localStorage.userToken` (campo `value`).

Envelope: `{code: 0, msg: "", data: {biz_code: 0, biz_msg: "", biz_data: {...}}}`.

## Volume capturado

- **79 chat sessions** discovered
- **0 pinned** nesta base (mas schema tem)

## Schema raw — chat_session

```python
{
    "id": str,                       # UUID
    "title": str,
    "title_type": str,               # 'SYSTEM' (auto-gerado) | provavelmente 'USER' (rename)
    "model_type": str,               # 'default' / outros (R1?)
    "agent": str,                    # 'chat' | 'agent' (modes do DeepSeek)
    "version": int,
    "is_empty": bool,
    "pinned": bool,                  # ✅ pin
    "current_message_id": int,       # leaf da branch ativa (igual claude.ai)
    "seq_id": int,                   # sequencial global por user
    "inserted_at": float,            # epoch (note: float)
    "updated_at": float
}
```

## Schema raw — chat_message (campos completos)

```python
{
    "message_id": int,                       # **integer**, sequencial dentro da conv (1, 2, 3...)
    "parent_id": int | null,                 # **branches** (DAG plano)
    "role": str,                             # 'USER' | 'ASSISTANT' (uppercase!)
    "content": str,                          # texto do msg
    "model": str,                            # ex 'deepseek-chat' / 'deepseek-reasoner'
    "inserted_at": float,
    "status": str,                           # 'FINISHED' | provavelmente 'GENERATING', etc
    
    # === R1 reasoning ===
    "thinking_content": str | null,          # **R1 reasoning chain** (texto cru)
    "thinking_elapsed_secs": float | null,   # **latencia exata do thinking**
    "thinking_enabled": bool,                # se R1 estava ligado
    
    # === Search ===
    "search_enabled": bool,                  # se web search estava ligado
    "search_results": list[dict] | null,     # **citations completas**
    "search_status": str | null,             # enum: progressao
    
    # === Tokens ===
    "accumulated_token_usage": int,          # **total tokens cumulativos**
    
    # === Files ===
    "files": list[dict],                     # uploads
    
    # === UI/UX flags ===
    "feedback": dict | null,                 # thumbs up/down do user
    "incomplete_message": str | null,        # se msg foi cortada
    "tips": list,                            # sugestoes da plataforma
    "ban_edit": bool,                        # se UI bloqueia edit
    "ban_regenerate": bool,                  # se UI bloqueia regenerate
}
```

## Confirmacao R1 reasoning

Sample de `chat_session_id=755ea129...`, msg 2 (assistant):
- `thinking_enabled: True`
- `thinking_elapsed_secs: 5.89`
- `thinking_content[:200]`: "Hmm, o usuário compartilhou um link do GitHub para um plugin do Obsidian..."
- `accumulated_token_usage: 3542`

✅ R1 reasoning chain, latencia, e token usage TODOS no schema. Parser legacy
ignora todos os 3.

## Gaps do parser legacy (`src/parsers/deepseek.py`, 134 linhas)

**Critico:** o parser legacy assume schema **antigo** com `mapping`, `node_id`,
`fragments` (REQUEST/RESPONSE/THINK/SEARCH). O schema atual eh um **array
flat** `chat_messages` com campos dedicados. **Parser legacy nao funciona
no formato atual.** Precisa rewrite total.

| Feature | Schema raw atual | Legacy parser |
|---|---|---|
| `chat_messages` array flat | ✅ | ❌ — espera `mapping` (formato antigo) |
| `parent_id` (branches DAG) | ✅ | parcial — `children[-1]` so |
| `thinking_content` | ✅ | parcial — assume fragments c/ type=THINK |
| `thinking_elapsed_secs` | ✅ | ❌ |
| `search_results` (list de dicts) | ✅ | ❌ — assume fragments c/ type=SEARCH (string) |
| `accumulated_token_usage` | ✅ | ❌ |
| `pinned` (session level) | ✅ | ❌ |
| `agent` (chat vs agent mode) | ✅ | ❌ |
| `model_type` | ✅ | ❌ |
| `current_message_id` (leaf branch) | ✅ | ❌ |
| `incomplete_message` / `status` | ✅ | ❌ |
| `feedback` | ✅ | ❌ |
| `ban_edit` / `ban_regenerate` | ✅ | ❌ |
| `files` per msg | ✅ | ❌ |

## Plano parser v3 DeepSeek

1. **Schema canonico** — `mode` mapeado por `agent` (chat/agent) +
   `model_type` (default/reasoner)
2. **Branches** via `current_message_id` + `parent_id` (mesmo algoritmo
   Claude.ai/Qwen — DAG plano)
3. **`thinking_content`** → `Message.thinking`
4. **`thinking_elapsed_secs`** → metadata adicional (ja temos
   start/stop_timestamp por msg, mas thinking_elapsed eh especifico)
5. **`search_results`** → `ToolEvent` (event_type=`search_call/_result`)
   com citations completas em metadata_json
6. **`accumulated_token_usage`** → `Message.token_count` (ja existe no schema!)
7. **`pinned`** → `Conversation.is_pinned` (cross-platform)
8. **`incomplete_message`** + `status` → `Message.finish_reason`
9. **`feedback`** → preservar em metadata (settings_json ou attachments_json)

## Pasta unica + pasta de raw

Atual: `data/raw/DeepSeek Data/<YYYY-MM-DDTHH-MM>/` (legacy timestamp)
Alvo: `data/raw/DeepSeek/` (pasta unica) — espelhar Claude.ai/Perplexity

## DeepSeek nao tem projects nem folders

Diferente de Qwen/Claude.ai/ChatGPT — DeepSeek nao expoe sources/knowledge
files separados. Sem `project_id` no schema da session. Logica de pasta
unica fica mais simples (so threads).

## TODOs durante implementacao — STATUS

- [x] **Enum `status`:** confirmado 3 valores (`FINISHED`, `INCOMPLETE`,
  `WIP`). Parser via `normalize_status_to_finish_reason`.
- [x] **Enum `search_status`:** so `FINISHED` visto. Preservado em metadata.
- [x] **Schema de `files` per msg:** documentado — campos `name`,
  `file_name`, `url`, `file_url`, `file_id`, `size`, `file_type`. 47 msgs
  com files na base.
- [x] **`agent='agent'`:** schema tem mas 0 sessions com agent mode na base.
  Parser ja mapeia agent → mode='research' por precaucao.
- [x] **`model_type` variants:** descobertos `default` (78) E `expert` (1).
  `expert` = R1 reasoner mode. Parser mapeia expert/thinking/reasoner →
  mode='research'.
- [x] **CRUD historico via parent snapshots:** validado em
  `docs/platforms/deepseek/server-behavior.md` (2 snapshots, +1 added, 0 deletes).
- [ ] **Rename via UI:** `updated_at` bumpa? — manual TODO, nao bloqueia
