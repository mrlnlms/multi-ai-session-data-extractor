# Parser Claude.ai v3 — empirical findings (2026-05-01)

Findings coletados sobre o raw real (~835 convs + 83 projects capturados em
2026-05-01 via `scripts/claude-sync.py`). Espelha
`docs/parser-v3/empirical-findings.md` do ChatGPT.

## 1. Top-level conversation schema

Campos presentes em **toda** conv (probe sobre 18 amostras de tamanhos
e features variadas):

| Campo | Tipo | Notas |
|---|---|---|
| `uuid` | string | identificador estavel |
| `name` | string | titulo (pode estar vazio) |
| `summary` | string | summary auto-gerado pela plataforma (longo, multi-line) |
| `model` | string | ex `claude-sonnet-4-5-20250929` (so do **ultimo** turn assistant) |
| `platform` | string | sempre `'CLAUDE_AI'` (constant) |
| `created_at`, `updated_at` | ISO datetime UTC | `Z` suffix |
| `current_leaf_message_uuid` | UUID | aponta pra ultima msg da branch ativa — **chave pra branches** |
| `is_starred` | bool | **mapeia pra `Conversation.is_pinned`** (cross-platform check) |
| `is_temporary` | bool | feature "Temporary chat" — preservar como flag em Conversation |
| `project_uuid` | UUID? | FK pro project (null se conv standalone) |
| `project` | dict? | `{uuid, name}` (minimal — full metadata em `projects/<uuid>.json`) |
| `settings` | dict | feature flags por conv (web_search, artifacts, latex, paprika_mode etc) |
| `chat_messages` | list | mensagens da conv |

**Campos preservation injetados pelo extractor/reconciler:**
- `_last_seen_in_server` (ISO date)
- `_preserved_missing` (bool)

## 2. Settings per-conv

`settings` eh um dict de feature flags. Observados:

```json
{
  "enabled_bananagrams": true,        // codename interno
  "enabled_web_search": true,
  "paprika_mode": "extended",          // 'extended' = extended thinking enabled
  "enabled_monkeys_in_a_barrel": true,
  "enabled_saffron": true,
  "tool_search_mode": "auto",          // 'auto' | outras?
  "preview_feature_uses_artifacts": true,
  "preview_feature_uses_latex": true,
  "enabled_artifacts_attachments": false,
  "enabled_turmeric": true
}
```

Nao todas as flags aparecem em toda conv. Codinomes (bananagrams, saffron,
turmeric, paprika, monkeys_in_a_barrel) sao aliases internos — preservar
como blob.

## 3. Message schema

```python
{
    "uuid": str,                      # identificador estavel
    "parent_message_uuid": str,       # 00000000-...-000000 = root; senao FK pra parent
    "sender": "human" | "assistant",
    "created_at": ISO,
    "updated_at": ISO,
    "index": str,                     # serializado como string ('0', '1', '2'...)
    "text": str,                      # legacy/redundante (concat de blocks text)
    "truncated": str ('True'/'False'),
    "sync_sources": list,             # observado vazio em todas as amostras
    "stop_reason": str?,              # so assistant: 'stop_sequence', etc
    "content": list[Block],           # array de blocks tipados
    "attachments": list[Attachment],  # uploads de **texto** com extracted_content inline
    "files": list[File],              # uploads de **binario** (imagens) — file_uuid, preview_url
}
```

### 3.1. Branches via parent_message_uuid

Diferente do ChatGPT (que usa tree-walk em `mapping`), Claude.ai eh **DAG
plano**:

- Cada msg tem `parent_message_uuid`
- Root: `parent_message_uuid = '00000000-0000-4000-8000-000000000000'`
- `current_leaf_message_uuid` (top-level) aponta pra ultima msg da branch ativa
- Branches off-path = msgs cujo descendente final nao eh o `current_leaf`

Pra parser v3:
- Build adjacency `{uuid → [children]}`
- Trace `current_leaf` ate root → branch principal
- Outras msgs com children divergentes → branches secundarias
- `branch_id`: `<conv>_main` pra principal, `<conv>_branch_<N>` ou hash pra secundarias

## 4. Content blocks

### 4.1. `text`
```json
{
  "type": "text",
  "text": "...conteudo Markdown...",
  "citations": [...],           // lista, geralmente vazia
  "start_timestamp": ISO,
  "stop_timestamp": ISO
}
```

### 4.2. `thinking` (extended thinking)
```json
{
  "type": "thinking",
  "thinking": "...texto cru do thinking...",
  "summaries": [...],           // resumo intercalado quando muito longo
  "cut_off": bool,              // se foi truncado por limite
  "truncated": bool,
  "start_timestamp": ISO,
  "stop_timestamp": ISO
}
```

**Mapeia pra `Message.thinking`** (campo ja existe no schema). Concat
de todos os blocks `thinking` da msg → `Message.thinking`.

### 4.3. `tool_use`
```json
{
  "type": "tool_use",
  "id": "toolu_...",
  "name": "web_search" | "artifacts" | "google_drive_search" | ...,
  "input": {...},               // payload do tool call
  "message": "Searching the web",  // descricao human-readable
  "icon_name": "globe",         // hint visual
  "start_timestamp": ISO,
  "stop_timestamp": ISO,
  // MCP-only:
  "integration_name": "Google Drive",
  "integration_icon_url": "https://..."
}
```

**Mapeia pra `ToolEvent`** (campo `direction='call'`). Detectar MCP via
presenca de `integration_name`.

Tools observados ate agora:
- `web_search` (built-in)
- `artifacts` (built-in — code/markdown gerado)
- `google_drive_search` (MCP — Google Drive)
- mais a descobrir conforme sync completa

### 4.4. `tool_result`
```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_...",      // FK pro tool_use
  "name": "web_search",
  "content": [                      // pode ser list de knowledge ou string
    {
      "type": "knowledge",
      "title": "...",
      "url": "https://...",
      "metadata": {...},
      "is_missing": false
    }
  ],
  "is_error": bool,
  "icon_name": "globe"
}
```

**Mapeia pra `ToolEvent`** (`direction='result'`, `tool_call_id=tool_use_id`).

### 4.5. `token_budget`
```json
{ "type": "token_budget" }
```

Observacao: payload vazio. Provavelmente sinaliza limite de contexto
atingido ou ponto de cut-off em thinking. **Skip no parser** (nao agrega
informacao ao schema canonico).

## 5. Attachments (text uploads — Tab "Attach")

```json
{
  "id": str,
  "file_name": str,
  "file_size": int,
  "file_type": "txt" | "pdf" | "docx" | ...,
  "extracted_content": str,         // **conteudo extraido inline** (texto cheio)
  "created_at": ISO
}
```

**Volume observado pelo plan §5:** 1.8k+ attachments com extracted_content.

**Mapeia pra Message:**
- `attachment_names`: lista de file_names
- `extracted_content` total: pode entrar em campo dedicado ou no Message.content

## 6. Files (binary uploads — imagens)

```json
{
  "uuid": str,
  "file_uuid": str,
  "file_kind": "image" | "document" | "blob",
  "file_name": str,
  "success": bool,
  "preview_url": "/api/{org}/files/{file_uuid}/preview",
  "thumbnail_url": "/api/{org}/files/{file_uuid}/thumbnail",
  "preview_asset": {
    "url", "file_variant": "preview",
    "primary_color", "image_width", "image_height"
  },
  "thumbnail_asset": {...},
  "created_at": ISO
}
```

**Asset paths:** `data/raw/Claude.ai/assets/{file_uuid}_preview.webp` (e
`_thumbnail.webp` se baixado). Mapear pra `Message.asset_paths`.

## 7. Project schema

`data/raw/Claude.ai/projects/<uuid>.json`:

```python
{
    "uuid": str,
    "name": str,
    "description": str,
    "prompt_template": str,             # custom instructions do project
    "created_at": ISO,
    "updated_at": ISO,
    "archived_at": ISO?,
    "archiver": dict?,                  # quem arquivou (so se archived)
    "creator": {"uuid", "full_name"},
    "is_private": bool,
    "is_starred": bool,
    "is_starter_project": bool,
    "is_harmony_project": bool,
    "permissions": list,
    "settings": dict,
    "subtype": str?,
    "type": str?,
    "organization_role": str,
    "docs": list[Doc],                  # text uploads com content inline
    "files": list[File],                # binary uploads (mesma shape do conv.files)
    "docs_count": str,                  # numero como string
    "files_count": str
}
```

### 7.1. Project docs

```python
{
    "uuid": str,
    "project_uuid": str,
    "file_name": str,
    "content": str,                     # **content inline cheio**
    "estimated_token_count": int,
    "created_at": ISO
}
```

**Volume:** observado 0–12 docs por project. Plan §5 menciona "23M chars
em 546 docs no projeto-mae" — pode justificar tabela `project_docs`
separada no parquet (vs colocar em Message).

## 8. Mapeamento → schema canonico v3

### 8.1. Conversation

```python
Conversation(
    conversation_id=conv['uuid'],
    source='claude_ai',
    title=conv.get('name') or None,
    created_at=ts(conv['created_at']),
    updated_at=ts(conv['updated_at']),
    message_count=len(messages),       # apos branches build
    model=conv.get('model'),
    account=self.account,
    mode='chat',                        # claude.ai nao expoe mode no schema
    url=f'https://claude.ai/chat/{uuid}',
    project_id=conv.get('project_uuid'),
    project_name=(conv.get('project') or {}).get('name'),
    is_pinned=conv.get('is_starred', False),    # << NOVO (cross-platform)
    is_temporary=conv.get('is_temporary', False),  # << NOVO
    is_archived=False,                  # claude.ai schema nao tem (ate now)
    summary=conv.get('summary'),        # campo existente no schema?
    is_preserved_missing=conv.get('_preserved_missing', False),
    last_seen_in_server=conv.get('_last_seen_in_server'),
    custom_gpt_id=None,                 # not applicable
    custom_gpt_name=None,
)
```

### 8.2. Message

```python
Message(
    message_id=msg['uuid'],
    conversation_id=conv['uuid'],
    source='claude_ai',
    sequence=int(msg['index']),         # ja vem como string
    role={'human': 'user', 'assistant': 'assistant'}[msg['sender']],
    content=concat_text_blocks(msg['content']),
    model=conv.get('model') if role == 'assistant' else None,
    created_at=ts(msg['created_at']),
    account=self.account,
    content_types=','.join(sorted(set(b['type'] for b in msg['content']))),
    attachment_names=json.dumps([a['file_name'] for a in msg.get('attachments', [])]),
    asset_paths=resolve_file_assets(msg['files']),
    thinking=concat_thinking_blocks(msg['content']),
    parent_message_uuid=msg.get('parent_message_uuid'),
    branch_id=resolve_branch_id(...),
    stop_reason=msg.get('stop_reason'),
)
```

### 8.3. ToolEvent (1 por tool_use OU tool_result)

```python
ToolEvent(
    event_id=block['id'] if direction == 'call' else block['tool_use_id'] + '_result',
    message_id=msg['uuid'],
    conversation_id=conv['uuid'],
    source='claude_ai',
    sequence=N,                         # dentro da msg
    direction='call' | 'result',
    tool_name=block['name'],
    tool_call_id=block.get('id') or block.get('tool_use_id'),
    timestamp=ts(block.get('start_timestamp') or block.get('stop_timestamp')),
    payload=json.dumps(block.get('input') or block.get('content')),
    is_mcp=bool(block.get('integration_name')),
    integration_name=block.get('integration_name'),
    is_error=block.get('is_error', False),
)
```

### 8.4. Branch

```python
Branch(
    branch_id=...,                      # <conv>_main ou <conv>_branch_<short_uuid>
    conversation_id=conv['uuid'],
    source='claude_ai',
    is_main=...,
    leaf_message_uuid=...,
    parent_message_uuid=...,
    message_count=...,
)
```

## 9. Pendentes / TODOs

- **Project docs grande volume:** decidir se entra como tabela
  `project_docs` separada no parquet ou se vai inline em
  `Conversation.project_*`. Validar na rodada full quando vier o
  total real (vs 23M chars do projeto pai).
- **Citations em text blocks:** observado vazio em amostras pequenas.
  Validar se aparece em pesquisa academica / web search.
- **Block `token_budget`:** documentado como skip — confirmar que nao
  carrega info perdida.
- **`sync_sources`:** observado vazio em toda amostra. Investigar
  contexto onde aparece (Google Drive sync? Project sync?).
- **MCP coverage real:** ver no full sync quantos MCPs aparecem alem
  de `google_drive_search`.

## 10. Comportamento do servidor (a validar empiricamente)

Pendente: testar cenarios CRUD igual fizemos com ChatGPT/Perplexity:

- Conv deletada → `_preserved_missing` no merged?
- Conv renomeada → servidor bumpa `updated_at`? (hipotese: sim, igual outros)
- Conv pinned (`is_starred=true`) → reflete em discovery?
- Conv temporary (`is_temporary=true`) → comportamento na captura
  (esquece quando termina sessao? persiste no servidor?)
- Project archive → `archived_at` populado mas continua acessivel?
- Project deletado → preserved_missing ou ENTRY_DELETED?

Sera documentado em `docs/claude-ai-server-behavior.md` apos ciclo
de testes manuais.
