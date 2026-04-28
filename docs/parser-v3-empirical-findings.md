# Parser v3 — Achados empíricos

Coleta empírica em `data/merged/ChatGPT/chatgpt_merged.json` (1171 convs,
27/abr–28/abr/2026). Documenta shape real de cada feature antes do plan
formal. Plan deve citar este doc como referência.

Fixtures sanitizadas em `tests/extractors/chatgpt/fixtures/raw_with_*.json`
+ meta-tests em `test_fixtures_integrity.py` (24 testes passando).

---

## 1. Branches

**Onde:** `mapping[node_id].children` é lista de IDs filhos. Branch =
qualquer node com `len(children) >= 2`.

**Frequência:** 43 convs (de 1171, ~3.7%).

**Estrutura:**
```json
{
  "mapping": {
    "node-A": {
      "id": "node-A",
      "parent": "node-root",
      "children": ["node-B1", "node-B2"]    // 2 forks
    },
    "node-B1": { "parent": "node-A", "children": [...] },
    "node-B2": { "parent": "node-A", "children": [...] }
  },
  "current_node": "node-B2-leaf-eventualmente"
}
```

**Como caminhar:**
- v2 atual: `current_node` → root via `.parent` (linear, ignora forks off-path)
- v3: tree-walk completo a partir do root; cada path único = uma branch
- Branch ativa = a que contém `current_node`

**Decisão informada:** branches viram tabela própria, `Message.branch_id` é
não-opcional (default `<conv_id>_main`).

---

## 2. Voice (audio_transcription)

**Onde:** `parts[]` da content da msg, como dict.

**Frequência:** 9 convs.

**Shape observado:**
```json
{
  "content_type": "audio_transcription",
  "text": "transcript do que foi dito",
  "direction": "in"
}
```

**Achado novo:** `direction` é `"in"` (user falando) ou `"out"` (assistant
falando). Não estava na decisão original — vale capturar como dimensão
extra.

**Decisão informada:** adicionar `is_voice: bool` em Message + capturar
`direction` em campo opcional ou como `voice_direction: Optional[str]`.

---

## 3. DALL-E (image_asset_pointer)

**Onde:** `parts[]` da content, como dict.

**Frequência:** 11 convs (com poucos nodes).

**Shape observado:**
```json
{
  "content_type": "image_asset_pointer",
  "asset_pointer": "sediment://file_<hash>",
  "size_bytes": 2175052,
  "width": 1024,
  "height": 1536,
  "metadata": {
    "dalle": {
      "gen_id": "<uuid>",
      "prompt": "<prompt original>",
      "serialization_title": "DALL-E generation metadata"
    },
    "generation": {
      "gen_id": "<uuid>",
      "gen_size": "xlimage",
      "height": 1536,
      "width": 1024,
      "transparent_background": false
    },
    "container_pixel_height": 1024,
    "container_pixel_width": 1024,
    "sanitized": true
  }
}
```

**Decisão informada:**
- `asset_pointer` (`sediment://file_XXX`) precisa virar path resolvido em
  `data/raw/ChatGPT/assets/images/.../<file_id>.png` (já tem mapeamento no
  sync de assets)
- `Message.asset_paths: Optional[list[str]]` recebe esse path resolvido
- Metadata.dalle.prompt é PII potencial (texto do user) — preservar no
  schema, mas `Message.content` deve incluir só "[imagem gerada]" ou similar

---

## 4. Canvas

**Onde:** múltiplos sinais possíveis:
- `recipient` começa com `canmore.` (ex: `canmore.create_textdoc`)
- `author.name` começa com `canmore.`
- `metadata.model_slug == "gpt-4o-canmore"` (variante específica)

**Frequência:** 8 convs.

**Tools relacionados (autores `canmore.*`):**
- `canmore.create_textdoc` — cria canvas
- `canmore.update_textdoc` — patch
- `canmore.get_textdoc_content` — leitura
- `canmore.comment_textdoc` — anotação

**Decisão informada:** tratar canvas como ToolEvent (não inline em
Message). `tool_name = "canmore.<action>"`. Conteúdo do canvas (textdoc)
fica em `result` ou `metadata_json` do ToolEvent.

---

## 5. Deep Research

**Onde:**
- `metadata.model_slug == "research"` ou similar
- `metadata.deep_research_version` setado
- `recipient == "research_kickoff_tool.*"`

**Frequência:** 36 convs.

**Tools relacionados:**
- `research_kickoff_tool` — base
- `research_kickoff_tool.clarify_with_text`
- `research_kickoff_tool.start_research_task`

**Decisão informada:** tratar como ToolEvent (`tool_name =
"research_kickoff_tool.*"`). Output do DR (PDFs gerados) já está em
`data/raw/ChatGPT/assets/deep_research/` — link via `asset_paths`.

---

## 6. Tether quote (citação estruturada)

**ACHADO IMPORTANTE:** tether_quote **NÃO está em metadata**. É um
**`content_type` próprio** — tipo de mensagem dedicado.

**Onde:** `mapping[node].message.content` quando `content_type ==
"tether_quote"`.

**Frequência:** 80 convs. **Total de 548 msgs com content_type=tether_quote
em todo merged.**

**Shape observado:**
```json
{
  "content_type": "tether_quote",
  "url": "file-<id>",                  // arquivo fonte
  "domain": "<nome do arquivo>.txt",   // PII (nome de arquivo)
  "text": "<texto citado>",            // PII
  "title": "<título extraído>"          // alguma vezes
}
```

**Decisão informada:**
- Tether_quote vira **ToolEvent** (não Message), pq é estrutura de "fonte"
  não de "fala": `tool_name = "tether_quote"`, `result = text`
- Ou: criar tabela própria `MessageQuote` se tiver muito frequente (548
  ocorrências sugere que vale)
- Adicionar `tether_quote_text` e `tether_quote_source_message_id` em
  Message está **superado** — content_type já é cidadão de primeira

---

## 7. Custom GPT (gizmo_id)

**ACHADO CRÍTICO:** o campo `gizmo_id` mistura **dois conceitos
diferentes** — distinguíveis pelo prefix:

| Prefix | Tipo | Frequência |
|---|---|---|
| `g-p-*` | Project (pasta com sources) | 49 IDs únicos, 1045 convs |
| `g-*` | Custom GPT verdadeiro | 1 ID único, 1 conv |

**Implicação:** o "gizmo_id" como dimensão de Custom GPT precisa filtrar
por prefix. **Conv com `gizmo_id` começando em `g-p-` NÃO é Custom GPT —
é só vinculada a um project**.

**Validação por msg:** confirmei empiricamente que `conv.gizmo_id ==
msg.metadata.gizmo_id` em todas as msgs (consistência).

**Decisão informada:**
- `Conversation.gizmo_id: Optional[str]` — só preencher se prefix `g-`
  (não `g-p-`), pra refletir Custom GPT real
- `Conversation.project_id: Optional[str]` — preencher com `g-p-*`
- `Conversation.gizmo_name`, `gizmo_resolved` — só pra Custom GPT

**Cenário "Custom GPT deletado" não foi observado** — fixture
`raw_with_custom_gpt.json` cobre só o caso "resolved". Quando user
deletar Custom GPT no servidor e rodarmos sync, geramos a 2ª fixture.

---

## 8. Tools (author.role=tool)

**Onde:** `mapping[node].message.author.role == "tool"`.

**Frequência:** 283 convs (~24% do total).

**Tool names únicos observados (35+):**

System / built-in:
- `bio` (memory write)
- `browser`, `browser.find`, `browser.open`, `browser.search`
- `python` (Code Interpreter)
- `dalle.text2im`
- `web`, `web.run`
- `file_search`, `myfiles_browser`
- `voice_mode.hangup`

Canvas:
- `canmore.create_textdoc`, `canmore.update_textdoc`
- `canmore.get_textdoc_content`, `canmore.comment_textdoc`

Deep Research:
- `research_kickoff_tool`, `research_kickoff_tool.start_research_task`,
  `research_kickoff_tool.clarify_with_text`

Computer Use (agentic):
- `computer.get`, `computer.sync_file`
- `container.exec`, `container.download`, `container.open_image`

JIT plugins (códigos opacos):
- `kaur1br5_context`, `q7dr546`, `n7jupd.metadata`
- `ct2_alici_ai__jit_plugin.newDiagrams`
- `r_1lm_io__jit_plugin.post_ReadPages`
- `t2uay3k.sj1i4kz`, `a8km123`

**Content types em msgs com role=tool:**
- `text` (mais comum)
- `code` (Code Interpreter input)
- `multimodal_text`
- `computer_output`, `execution_output` (saída de execução)
- `tether_quote`, `tether_browsing_display` (browse)
- `super_widget`, `system_error`

**Recipients observados (≠ "all"):**
- `assistant` (tool retornando pra assistant)
- `bio`, `browser`, `python`, `web`, `dalle.text2im`, ... (assistant
  chamando tool)
- 30+ valores distintos

**Decisão informada:**
- Cada msg com `role=tool` vira `ToolEvent`
- `tool_name = author.name` (preservado, não é PII)
- `result` = text do content (`parts[0]` se str, ou texto extraído)
- `metadata_json` = JSON dump da metadata da msg
- ToolEvent linkado ao Message pai via `message_id` = node parent que
  invocou (rastrear via `mapping[node].parent`)

---

## 9. Outros campos importantes

### finish_details

**Frequência:** alta em msgs assistant (não contado, mas presente em
maioria).

**Shapes observados:**
```json
{"type": "stop"}                              // mais comum
{"stop_tokens": [200007], "type": "stop"}    // com stop_tokens explícitos
{"stop": "<|im_end|>", "type": "stop"}       // com stop string
{"stop": "<|fim_suffix|>", "type": "stop"}   // FIM mode
{"type": "max_tokens"}                       // ⚠️ truncated por limite
```

**Decisão informada:**
- `Message.finish_reason: Optional[str]` recebe só o `type`
- Valores observados: `"stop"`, `"max_tokens"` (não vimos `content_filter`
  ainda mas é reportado pela OpenAI)

### message_source

**Não existe nos dados.** O campo `metadata.message_source` foi
verificado em todas as msgs — sempre vazio.

**Decisão informada:** **NÃO adicionar campo `message_source` em
Message**. Sem dado, sem campo. Se aparecer no futuro, adicionar então.

### weight

**Valores observados:** `0.0` ou `1.0` apenas.

**Decisão informada:** `is_hidden = (weight == 0.0)` é um dos sinais de
hidden_reason. Combinar com `is_visually_hidden_from_conversation` e
`recipient != all` (system pings).

### model_slug

**20+ valores únicos.** Top 5: `gpt-4o`, `text-davinci-002-render-sha`
(legacy), `gpt-5-1`, `gpt-5-2`, `gpt-5`.

**Modelos especiais:**
- `gpt-4o-canmore` → Canvas mode
- `research` → Deep Research
- `agent-mode` → Computer Use
- `o1`, `o1-preview`, `o3` → reasoning models

**Decisão informada:** `Message.model = metadata.model_slug` (string
livre, sem validação contra enum — modelos novos surgem).

### content_types (em todos os msgs)

13 tipos distintos. Counts:
- `text`: 19285 (dominante)
- `code`: 993
- `model_editable_context`: 661 (system bridge)
- `multimodal_text`: 657
- `tether_quote`: 548
- `execution_output`: 514
- `tether_browsing_display`: 330
- `thoughts`: 309
- `reasoning_recap`: 123
- `user_editable_context`: 18
- `system_error`: 14
- `super_widget`: 12
- `computer_output`: 1

**Decisão informada:** o parser deve ter um dispatcher por content_type,
não tratamento inline. v2 já tem isso parcial em `_extract_text` — v3
expande pra cobrir todos os 13.

---

## 10. Resumo de decisões finais (atualizadas pelos achados)

### Conversation +3 (mantido + 1 ajuste)
```python
gizmo_id: Optional[str] = None        # SOMENTE Custom GPT real (g-* não g-p-*)
gizmo_name: Optional[str] = None
gizmo_resolved: bool = True
project_id: Optional[str] = None      # NOVO — separa de gizmo_id (gizmo_id era ambíguo)
```

### Message +6 (ajustes nos achados)
```python
branch_id: str                                # NÃO opcional, default "<conv>_main"
asset_paths: Optional[list[str]] = None       # list[str], não string delimitada
finish_reason: Optional[str] = None           # de finish_details.type
is_hidden: bool = False
hidden_reason: Optional[str] = None           # 'visually_hidden', 'weight_zero', 'internal_recipient'
is_voice: bool = False
voice_direction: Optional[str] = None         # NOVO — 'in' ou 'out'

# REMOVIDOS pelos achados:
# tether_quote_text, tether_quote_source_message_id → tether_quote vira ToolEvent
# message_source → não existe nos dados
```

### ToolEvent +1 (mantido)
```python
result: Optional[str] = None  # complementa metadata_json existente
```

### Branch (nova tabela, mantido)
```python
branch_id, conversation_id, source, root_message_id,
leaf_message_id, is_active, created_at, parent_branch_id
```

---

## 11. Items pendentes pra próxima validação empírica

Pontos que precisam de mais dados antes de cravar no plan:

1. **Custom GPT deletado** — só 1 conv com `g-*` na base. Quando user
   deletar Custom GPT e rodarmos sync, validar comportamento (gizmo_name
   resolvido fica None?)
2. **content_filter** em finish_details — não observado, mas pode aparecer.
   Adicionar valor possível na docstring sem ainda incluir teste.
3. **Recipients com prefix de plugin** — ver se há padrão (`<plugin>.<action>`)
   pra extrair plugin_name como dimensão separada
4. **multimodal_text shape** — 657 msgs, não foi inspecionado em detalhe.
   Provável: parts[] mistura strings + dicts (texto + image refs).
   Validar antes de implementar.

---

## 12. Lista de fixtures geradas

Em `tests/extractors/chatgpt/fixtures/`:

| Fixture | Conv ID original (prefix) | Nodes | Feature alvo |
|---|---|---|---|
| `raw_with_branches.json` | 670efa03-508c | 5 | ≥1 node com 2+ children |
| `raw_with_voice.json` | 69499a7b-5ac4 | 14 | audio_transcription em parts |
| `raw_with_dalle.json` | 68258145-4d40 | 8 | image_asset_pointer + dalle |
| `raw_with_canvas.json` | 67ed845a-b978 | 11 | recipient/author canmore.* |
| `raw_with_deep_research.json` | 698c0802-35d8 | 7 | model_slug research |
| `raw_with_tether_quote.json` | 67dada8d-bf44 | 8 | content_type tether_quote |
| `raw_with_custom_gpt.json` | 691ea2cb-0a78 | 12 | gizmo_id g-* (não g-p-*) |
| `raw_with_tools.json` | 66eaed5e-5110 | 5 | author.role=tool |

24 meta-tests em `test_fixtures_integrity.py` validam que cada fixture
contém o feature alvo + sanity (title redactado, keys top-level
presentes).
