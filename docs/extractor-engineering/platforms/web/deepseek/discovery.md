# DeepSeek — discovery e schema raw

Probe inicial em 2026-05-01 com `deepseek-export.py --smoke 5` e inspecao do
raw em perfil local de teste. O estado atual da cobertura fica em
[state.md](state.md); CRUD e comportamento upstream ficam em
[server-behavior.md](server-behavior.md).

## Endpoints observados

| Endpoint | Papel |
|---|---|
| `GET /api/v0/chat_session/fetch_page?...pinned=false` | listar sessoes paginadas |
| `GET /api/v0/chat_session/fetch_page?...pinned=true` | listar sessoes pinadas |
| `GET /api/v0/chat/history_messages?chat_session_id=X` | buscar mensagens da sessao |

A resposta usa o envelope `data.biz_data`; a sessao autenticada fornece o
Bearer token. O perfil pode existir com token expirado, portanto uma leitura
minima da API deve preceder uma coleta relevante.

## Schema relevante

O formato atual e `chat_messages` plano, nao um `mapping` de nos. Cada sessao
carrega identificadores de ramo (`current_message_id`, `parent_id`), flags de
pin e modo/modelo; cada mensagem pode trazer `content`, `thinking_content`,
`thinking_elapsed_secs`, `accumulated_token_usage`, `search_results`, status,
feedback e arquivos.

O reasoning R1 foi observado com `thinking_enabled`, texto de pensamento,
duracao e uso acumulado de tokens. Esses campos justificam a preservacao de
thinking, tokens, eventos de busca, finish reason e anexos pelo parser.

## Limites observados

DeepSeek nao expoe projetos, pastas ou fontes de conhecimento separadas. O
modelo de preservacao e, portanto, centrado em sessoes e suas mensagens.

Planos de migracao do parser que acompanhavam este probe foram concluidos; a
cobertura canonica atual pertence ao `state.md` e os gaps remanescentes a
`known-limitations.md`.
