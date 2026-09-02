# Qwen — discovery e schema raw

Probe inicial em 2026-05-01 com `qwen-export.py --smoke 5` e inspecao do raw
em perfil local de teste. O estado atual da cobertura fica em [state.md](state.md)
e CRUD/comportamento upstream em [server-behavior.md](server-behavior.md).

## Endpoints observados

| Endpoint | Papel |
|---|---|
| `GET /api/v2/chats/?page=N` | listar chats fora de projeto |
| `GET /api/v2/chats/?page=N&project_id=X` | listar chats de projeto |
| `GET /api/v2/chats/pinned` | listar pinados |
| `GET /api/v2/chats/{id}` | buscar chat completo |
| `GET /api/v2/projects/` e `/projects/{id}/files` | projetos e arquivos |

A autenticacao usa o token da sessao web. Os headers e a estrutura devem ser
revalidados por probe quando uma mudanca upstream afetar a captura.

## Schema relevante

Chats carregam `chat_type`, pin/archive, referencias a projeto/pasta/share e
uma DAG de mensagens (`currentId`, `parentId`, `childrenIds`). Mensagens podem
conter `reasoning_content`, `content_list` com timestamps, resultados de busca
em `info`, configuracao de feature, anotacoes e estado de conclusao.

Projetos carregam nome, instrucao personalizada e a lista `_files` enriquecida
pelo extractor. URLs de arquivo sao preassinadas e devem ser baixadas de forma
idempotente pelo manifest.

## Amostras e limites

O probe confirmou oito `chat_type` e casos de `t2i`, `t2v`, artifacts e chats
em projeto. Campos como folder e share podem estar presentes sem ocorrencia em
uma amostra; preserva-los nao substitui uma validacao empirica da UI.

Planos de parser e TODOs de migracao deste probe foram concluidos. A cobertura
atual pertence ao `state.md`, comportamento validado ao `server-behavior.md`
e limites ainda abertos a `known-limitations.md`.
