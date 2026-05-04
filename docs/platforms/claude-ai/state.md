# Claude.ai — cobertura técnica

## Pipeline

- **Pasta única cumulativa:** `data/raw/Claude.ai/` e `data/merged/Claude.ai/`.
- **Sync orquestrador (3 etapas):** `scripts/claude-sync.py` (capture +
  assets + reconcile).
- **Captura headless** (sem Cloudflare challenge em runtime).
- **Auth:** profile persistente em `.storage/claude-ai-profile-<conta>/`
  (gerado via `scripts/claude-login.py`).

## Cobertura

Conversations + projects descobertos e capturados via discovery padrão.
Recovery automático de timeouts transientes via `scripts/claude-refetch-known.py`.

Binários + artifacts (code/markdown/html/react via `tool_use`) extraídos
durante asset download.

Reconciler v3 (FEATURES_VERSION=2): preservation completa (convs +
projects), idempotente. Output: `data/merged/Claude.ai/conversations/<uuid>.json`
+ `projects/<uuid>.json` + `assets/`.

### Volume de referência

- ~835 conversations + ~83 projects.
- ~24.5k messages / ~16k tool_events / ~1.16k branches.
- ~546 project_docs (~23M chars de content inline).

## Parser canônico v3.1

`src/parsers/claude_ai.py` + `_claude_ai_helpers.py`.

### Cobertura

- **Branches via DAG plano** (`parent_message_uuid` +
  `current_leaf_message_uuid`) — diferente do tree-walk do ChatGPT. ~28%
  convs com fork.
- **Thinking blocks** preservados em `Message.thinking`.
- **Tool use/result** → ToolEvent. Categorias observadas:
  `code_call/_result` (Computer Use/file editing), `artifact_call/_result`,
  `search` (web_search + research), `mcp_*` (Google Drive e outros).
- **MCP detection com 3 sinais** (`integration_name` + `mcp_server_url` +
  `is_mcp_app`).
- **Attachments com extracted_content** preservados in-place no merged;
  parser registra `file_names` em `Message.attachment_names`.
- **Files (uploads binários)** → `Message.asset_paths` resolvidos a
  partir de `file_uuid`.
- **`is_starred` → `is_pinned`** (cross-platform).
- **`is_temporary`** preservado (feature efêmera).
- **Project metadata** em `claude_ai_project_metadata.parquet`
  (`docs_count` + `files_count` + `prompt_template`).
- **Project docs** em `claude_ai_project_docs.parquet` (content inline,
  queryable).

### v3.1 gap-fill

- `Conversation.summary` auto-gerado pelo servidor (~56% das convs).
- `Conversation.settings_json` feature flags por conv (100%).
- `Message.citations_json` citations em text blocks.
- `Message.attachments_json` com `extracted_content` inline.
- `Message.start_timestamp` + `stop_timestamp` (latência por block, ~98%
  de cobertura, mediana ~30s assistant).

## Quarto descritivo

`notebooks/claude-ai.qmd`: 46MB HTML self-contained, render < 30s. Cor
primária: Anthropic burnt orange `#CC785C`.

## Cenários CRUD pendentes (validação manual)

Não validados empiricamente ainda — hipóteses esperadas:

- rename → servidor bumpa `updated_at`? (hipótese: sim).
- delete → reconciler marca como `_preserved_missing`?
- pin via UI → `is_starred=true` reflete em discovery?
- temporary chat → comportamento na captura?
- project archive → `archived_at` populado?

## Comandos

```bash
PYTHONPATH=. .venv/bin/python scripts/claude-sync.py
# Se o sync deixou gaps (timeouts transientes):
PYTHONPATH=. .venv/bin/python scripts/claude-refetch-known.py
PYTHONPATH=. .venv/bin/python scripts/claude-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/claude-ai.qmd
```
