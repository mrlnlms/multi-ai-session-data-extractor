# Plan: parser ChatGPT v3 (raw → parquet)

> **Status: IMPLEMENTADO em 2026-04-28.** Parser v3 promovido a `chatgpt`
> canônico. Ver `src/parsers/chatgpt.py`, `docs/parser-v3/validation.md`,
> e os 3 commits backdated em `feat/parser-v3-canonico` (mergeada em main).
> Versões antigas em `_backup-temp/parser-v3-promocao-2026-04-28/` (gitignored).
> Os critérios de pronto das Fases 2a, 2b, 2c, 2d foram atendidos. Este doc
> fica como histórico do plan formal — não editar pra refletir estado.

Plan formal pra implementação do parser v3 do ChatGPT. **Informado por
dados empíricos** coletados em [empirical-findings.md](empirical-findings.md).

Outra sessão (paralela à de dashboard) implementa este plan.

---

## 1. Contexto

### 1.1. Onde o parser se encaixa

```
data/raw/ChatGPT/chatgpt_raw.json
        ↓ (sync + reconcile)
data/merged/ChatGPT/chatgpt_merged.json     ← INPUT do parser
        ↓ (parser v3)
data/processed/ChatGPT/
        ├── conversations.parquet            ← OUTPUT
        ├── messages.parquet
        ├── tool_events.parquet
        ├── branches.parquet                 ← NOVA tabela
        └── conversation_projects.parquet    ← (já existe no schema)
```

Output são parquets canônicos — **interface universal** consumida por:
- Dashboard descritivo (Quarto + Streamlit deste projeto)
- AI Interaction Analysis (projeto separado, framework qualitativo)
- Qualquer análise downstream

### 1.2. Estado atual (o que já existe)

```
src/parsers/chatgpt.py       ← legacy, lê GPT2Claude bookmarklet (DEPRECATED)
src/parsers/chatgpt_v2.py    ← MVP, lê chatgpt_merged.json (BASE pra v3)
src/parsers/chatgpt_v3.py    ← NÃO EXISTE — esta é a entrega
```

**v2 já cobre (mantém em v3):**
- Tree-walk `current_node` → root
- Filtro `is_visually_hidden_from_conversation`
- Voice via `audio_transcription` em parts
- Filtro `role` ∈ {user, assistant, tool}
- Model por conv = último model_slug do assistant
- Project enrichment via `_project_name`

**v2 não cobre (alvo do v3):**
- Branches (linealiza, perde forks)
- Tether quote (ignora 548 ocorrências)
- ToolEvents estruturados (msgs com role=tool não viram ToolEvent)
- DALL-E inline (`image_asset_pointer` ignorado)
- Canvas (`canmore.*` tools não tratados)
- Deep Research (`research_kickoff_tool` não tratado)
- Custom GPT vs Project distinction
- finish_reason, weight, hidden_reason, voice_direction

### 1.3. Princípio "herda v2, expande"

**v3 NÃO é rewrite from scratch.** v2 tem código testado e funcional —
v3 estende. Especificamente:
- Mantém `_extract_text` (com adições pra novos content_types)
- Mantém estrutura geral (`parse`, `_extract_messages`)
- Adiciona métodos novos: `_extract_branches`, `_extract_tool_events`,
  `_resolve_asset_paths`, `_extract_finish_reason`, etc

`source_name` muda pra `chatgpt_v3` durante validação. Quando atingir
paridade + 100% confiança, **v3 vira `chatgpt`** (nome estável); v1 e v2
viram deprecated.

---

## 2. Princípios de design

### 2.1. Fidelidade ao raw

Schema canônico **representa fielmente o que o servidor entregou**. Não
inventa campos, não interpreta semanticamente, não consolida — só
estrutura.

### 2.2. Idempotência

Rodar parser 2x sobre mesmo merged produz parquets idênticos. Sem
side-effects, sem timestamps de processing no output.

### 2.3. Schema canônico é interface

`src/schema/models.py` define a fronteira. Mudar schema **quebra
contrato** com downstream — só com versionamento explícito (parquet path
diferente, ex: `data/processed/ChatGPT/v3/`).

### 2.4. Não-opcional onde dado existe

`branch_id` em Message é não-opcional (default `<conv>_main`). Outras
plataformas que não têm branches preenchem com main artificial. Schema
fica honesto: toda msg pertence a uma branch, mesmo que sempre a única.

### 2.5. Test-driven via fixtures

Implementação **dirigida por fixtures** já coletadas em
`tests/extractors/chatgpt/fixtures/raw_with_*.json`. Cada feature tem
fixture + teste. Fail = não implementado corretamente.

---

## 3. Schema canônico atualizado

### 3.1. Conversation (+6 campos novos)

```python
@dataclass
class Conversation:
    # Existentes
    conversation_id: str
    source: str
    title: Optional[str]
    created_at: pd.Timestamp
    updated_at: pd.Timestamp
    message_count: int
    model: Optional[str]
    account: Optional[str] = None
    mode: Optional[str] = None
    project: Optional[str] = None         # nome do project (já existia)
    url: Optional[str] = None
    interaction_type: str = "human_ai"
    parent_session_id: Optional[str] = None

    # NOVOS (parser v3)
    project_id: Optional[str] = None              # g-p-* (separado de gizmo_id)
    gizmo_id: Optional[str] = None                # SOMENTE Custom GPT real (g-* não g-p-*)
    gizmo_name: Optional[str] = None              # nome do Custom GPT, se resolvido
    gizmo_resolved: bool = True                   # False se Custom GPT deletado no servidor
    is_preserved_missing: bool = False            # True se servidor não retornou na última run
    last_seen_in_server: Optional[pd.Timestamp] = None  # equivalente canônico de _last_seen_in_server
```

**Distinção crítica:**
- `project_id`: g-p-* (pasta com sources)
- `gizmo_id`: g-* não g-p-* (Custom GPT real)
- A mesma conv pode ter os dois (raro mas possível)

**Campos de preservation (importante pra dashboard descritivo):**
- `is_preserved_missing`: equivalente canônico do `_last_seen_in_server != today`
  do raw. Permite dashboards filtrarem "convs ativas no servidor" vs
  "preservadas localmente porque sumiram"
- `last_seen_in_server`: data ISO da última vez que servidor retornou essa
  conv. Pra preserved, fica fixa no momento de sumiço; pra ativas, atualiza
  a cada run.

Sem esses campos, downstream teria que reimplementar a heurística
`_last_seen_in_server vs today` que hoje é convenção do raw — campo
canônico evita acoplamento ao formato interno.

### 3.2. Message (+8 campos novos)

```python
@dataclass
class Message:
    # Existentes
    message_id: str
    conversation_id: str
    source: str
    sequence: int
    role: str
    content: str
    model: Optional[str]
    created_at: pd.Timestamp
    account: Optional[str] = None
    token_count: Optional[int] = None
    word_count: Optional[int] = None
    attachment_names: Optional[str] = None
    content_types: Optional[str] = None
    thinking: Optional[str] = None
    tool_results: Optional[str] = None

    # NOVOS (parser v3)
    branch_id: str                          # NÃO opcional, default "<conv>_main"
    asset_paths: Optional[list[str]] = None # list nativo (NÃO string delimitada)
    finish_reason: Optional[str] = None     # de finish_details.type
    is_hidden: bool = False
    hidden_reason: Optional[str] = None     # 'visually_hidden', 'weight_zero', 'internal_recipient'
    is_voice: bool = False
    voice_direction: Optional[str] = None   # 'in' (user) ou 'out' (assistant)
```

**Decisões superadas pelos achados:**
- ❌ `tether_quote_text/source_message_id` — `tether_quote` é `content_type`,
  vira ToolEvent
- ❌ `message_source` — não existe nos dados
- ❌ `branch_parent_uuid`/`branch_root_uuid` — informação fica em tabela Branch

### 3.3. ToolEvent (+1 campo)

```python
@dataclass
class ToolEvent:
    # Existentes
    event_id: str
    conversation_id: str
    message_id: str               # msg que invocou o tool
    source: str
    event_type: str               # categoria: search, code, canvas, dalle, etc
    tool_name: Optional[str]      # nome exato (browser, python, canmore.create_textdoc)
    file_path: Optional[str]
    command: Optional[str]
    metadata_json: Optional[str]  # já existe — estrutura complexa serializada

    # NOVO (parser v3)
    result: Optional[str] = None  # output texto simples (snippets, stdout breve)
```

**Distinção `result` vs `metadata_json`:**
- `result`: texto puro pra exibir (search snippets, code stdout, brief)
- `metadata_json`: JSON completo da metadata da msg (estrutura aninhada
  pra análise programática)

### 3.4. Branch (NOVA tabela)

```python
@dataclass
class Branch:
    branch_id: str                   # uuid próprio ou node_id raiz da branch
    conversation_id: str
    source: str
    root_message_id: str             # primeira msg da branch
    leaf_message_id: str             # última msg da branch
    is_active: bool                  # current_node está nesta branch?
    created_at: pd.Timestamp         # create_time da root
    parent_branch_id: Optional[str] = None  # null pra main, outra branch_id pra forks
```

**Convenção branch_id:**
- Main branch: `"<conv_id>_main"` (sempre presente, mesmo sem forks)
- Forks: `"<conv_id>_<node_id_do_root_da_branch>"`

---

## 4. Cobertura por feature

Cada feature tem fixture já coletada. Implementação deve fazer cada uma
passar nos testes.

### 4.1. Branches (`raw_with_branches.json`)

**Algoritmo:**
1. Identificar todos os nodes com `len(children) >= 2` no mapping
2. Pra cada fork, cada child gera uma branch
3. Branch root = primeira msg após o fork
4. Branch leaf = última msg seguindo `parent → children` recursivo
5. Branch é "active" se contém `current_node`
6. Branch principal (main) = caminho que parte do node sem parent até o
   primeiro fork (ou até `current_node` se não houver fork)

**Outputs:**
- 1 row por branch em `branches.parquet`
- Cada `Message.branch_id` aponta pra sua branch
- v2 só pegava branch ativa (path pro current_node) — v3 pega todas

**Edge cases:**
- Conv sem fork: 1 branch só (`<conv>_main`), todas msgs nela
- Múltiplos forks aninhados: cada fork gera novas branches, com
  `parent_branch_id` apontando pra origem

### 4.2. Voice (`raw_with_voice.json`)

**Algoritmo:**
1. Detectar `parts[i]` dict com `content_type=="audio_transcription"`
2. Extrair `text` → vai pra `Message.content`
3. Setar `Message.is_voice = True`
4. Setar `Message.voice_direction = parts[i].get("direction")`  (in/out)
5. Adicionar "audio_transcription" em `content_types` (CSV existente)

**Edge case:** msg pode ter parts mistas (texto + audio). Concatenar texts
respeitando ordem.

### 4.3. DALL-E (`raw_with_dalle.json`)

**ACHADO EMPÍRICO PÓS-FASE-2A:** DALL-E aparece em `role=tool` em 46/46
casos, NÃO em `role=assistant`. Plan original (que assumia Message +
asset_paths) foi revisado. Implementação cobre 2 casos distintos:

**Caso A — DALL-E (servidor gerou imagem):**
1. Detectar via **semântica** (não nome de tool):
   `image_asset_pointer` + `metadata.dalle` truthy em `parts[]`
2. Vira **ToolEvent** (não Message — role=tool):
   - `event_type = "image_generation"`
   - `tool_name = author.name` (preservado, mas sanitizado em fixture
     vira algo opaco — detecção semântica é o sinal real)
   - `file_path` resolvido: `asset_pointer = "sediment://file_<hash>"`
     → buscar em `data/raw/ChatGPT/assets/images/<conv_id>/file_<hash>.*`
   - `metadata_json` inclui `metadata.dalle` completo (gen_id, prompt, etc)
3. Linkado ao parent message_id (assistant que invocou)

**Caso B — User upload de imagem (user subiu imagem):**
1. Detectar `image_asset_pointer` SEM `metadata.dalle` em `role=user`
2. Vira **Message regular** (não ToolEvent):
   - `Message.asset_paths` recebe path resolvido
   - `Message.content_types` inclui marker `"image_upload"`
   - Distingue de DALL-E mesmo quando ambos têm `image_asset_pointer`

**Frequências reais (Fase 2a):**
- DALL-E (Caso A): 50 ToolEvents (45 com file_path resolvido, 5 sem
  porque asset removido)
- User uploads (Caso B): 402 Messages com `asset_paths` + marker

### 4.4. Canvas (`raw_with_canvas.json`)

**Algoritmo:**
1. Detectar Canvas via:
   - `recipient.startswith("canmore.")`, OR
   - `author.name.startswith("canmore.")`, OR
   - `metadata.model_slug == "gpt-4o-canmore"`
2. Cada msg envolvendo canmore.* vira ToolEvent
3. `event_type = "canvas"`
4. `tool_name = "canmore.<action>"` (create_textdoc, update_textdoc, etc)
5. `result = content text` (textdoc completo ou patch)
6. `metadata_json = msg.metadata` (mantém context completo)

**Asset paths:**
- Se canvas foi exportado pro disco (assets/canvases/), linkar via
  `asset_paths`. Senão, fica só em ToolEvent.

### 4.5. Deep Research (`raw_with_deep_research.json`)

**Algoritmo:**
1. Detectar via:
   - `metadata.model_slug == "research"`, OR
   - `metadata.deep_research_version` truthy, OR
   - `recipient.startswith("research_kickoff_tool")`
2. Msgs com `author.name == "research_kickoff_tool"` viram ToolEvent
3. `event_type = "deep_research"`
4. `tool_name = author.name` exato
5. Linkar PDFs gerados via `asset_paths` (em `assets/deep_research/`)

### 4.6. Tether quote (`raw_with_tether_quote.json`)

**ACHADO IMPORTANTE:** `content_type == "tether_quote"` é tipo de msg
próprio (não anexo). 548 ocorrências em 80 convs.

**Algoritmo:**
1. Detectar `content.content_type == "tether_quote"`
2. **Não vira Message normal** — vira ToolEvent
3. `event_type = "quote"`
4. `tool_name = "tether_quote"`
5. `result = content.text`
6. `metadata_json` inclui `url`, `domain`, `title` da quote
7. Atribuir `message_id` ao parent (mensagem que provocou a quote, via
   `mapping[node].parent`)

### 4.7. Custom GPT (`raw_with_custom_gpt.json`)

**Algoritmo:**
1. Ler `conv.gizmo_id`
2. Se `None`: `Conversation.gizmo_id = None`, `gizmo_resolved = True`
3. Se `g-p-*`: NÃO é Custom GPT — `Conversation.project_id = gizmo_id`,
   `Conversation.gizmo_id = None`
4. Se `g-*` mas não `g-p-*`: É Custom GPT real
   - `Conversation.gizmo_id = gizmo_id`
   - `Conversation.gizmo_name = ?` (se resolvível) — verificar campos
     possíveis no raw: `gizmo_name`, `metadata.gizmo_name`, etc. Se não
     existir, definir `gizmo_resolved = False`
5. Validação por consistência: todas as msgs da mesma conv devem ter o
   mesmo `metadata.gizmo_id`. Se discrepância: warning.

**Custom GPT deletado:** sem dados empíricos (só 1 Custom GPT na base
atual, todos resolvidos). Implementar com heurística "se nome não
encontrável, gizmo_resolved=False" — validar quando rolar.

### 4.8. Tools genéricos (`raw_with_tools.json`)

**Algoritmo:**
1. Pra cada msg com `author.role == "tool"`:
   - Não vira Message regular (filtrar do output `messages.parquet`)
   - Vira ToolEvent
2. `event_type` = categoria mapeada. Usar **detecção semântica primeiro**
   (presença de campos específicos), nome do tool como fallback:
   ```python
   # Detecção semântica primeiro (robusto contra fixtures sanitizadas
   # e nomes opacos de JIT plugins)
   if has_image_asset_pointer_with_dalle_metadata(msg):
       event_type = "image_generation"
   elif content_type == "tether_quote":
       event_type = "quote"

   # Senão, classifier por tool_name
   tool_name = author.name
   if "browser" in tool_name or tool_name in ("web", "web.run"):
       event_type = "search"
   elif tool_name in ("python", "execution"):
       event_type = "code"
   elif tool_name.startswith("canmore."):
       event_type = "canvas"
   elif tool_name.startswith("research_kickoff_tool"):
       event_type = "deep_research"
   elif tool_name == "bio":
       event_type = "memory"
   elif tool_name.startswith("file_search") or tool_name == "myfiles_browser":
       event_type = "file_search"
   elif tool_name.startswith(("computer.", "container.")):
       event_type = "computer_use"
   else:
       event_type = "other"  # plugins JIT, custom GPT plugins, etc
   ```

**Frequências observadas (Fase 2a, 3030 ToolEvents reais):**
- `quote`: 527
- `search`: 519
- `code`: 498
- `canvas`: 393
- `file_search`: 324
- `deep_research`: 291
- `other`: 275 (JIT plugins, custom)
- `memory`: 141
- `image_generation`: 50
- `computer_use`: 12
3. `tool_name = author.name` (exato, preservado)
4. `result = text extraído` da content (pode ser code, multimodal_text, etc)
5. `metadata_json = json.dumps(msg.metadata)`
6. `message_id = parent_id` (msg do assistant que invocou — caminhar via
   `mapping[node].parent`)

**Recipients ≠ "all":** msgs com `recipient` específico (browser, python,
etc) são **chamadas** do assistant pra tool — também viram ToolEvent
(mas com `role=assistant`, não tool). Decisão: o "evento" é a chamada +
resposta. Cada round-trip vira 1 ToolEvent (com result do tool).

---

## 5. Estrutura de arquivos novos

```
src/parsers/chatgpt_v3.py                    # parser principal
src/parsers/_chatgpt_helpers.py              # funções compartilhadas (extract_text, etc)

scripts/chatgpt-parse.py                      # CLI wrapper
                                                # - lê data/merged/ChatGPT/chatgpt_merged.json
                                                # - escreve data/processed/ChatGPT/*.parquet

tests/parsers/test_chatgpt_v3.py             # testes do parser usando fixtures
                                                # - 1 teste por feature (8 fixtures + cenários)

src/schema/models.py                          # ATUALIZADO com campos novos + Branch
                                                # - testes existentes em tests/schema/ devem
                                                #   continuar passando
```

### 5.1. Convenção de naming (já estabelecida)

O dashboard (Fase 1, já implementado) descobre os mergeds via
`merged_dir.glob("*_merged.json")`. Implica padrão **`<source_lower>_merged.json`**:

```
data/merged/ChatGPT/chatgpt_merged.json
data/merged/Claude.ai/claude_ai_merged.json   (futuro)
data/merged/Gemini/gemini_merged.json         (futuro)
```

E pros parquets de saída do parser:
```
data/processed/<Source>/conversations.parquet
data/processed/<Source>/messages.parquet
data/processed/<Source>/tool_events.parquet
data/processed/<Source>/branches.parquet
```

**Regra:** o pacote de saída do parser usa o nome canônico do source
(capitalizado em pasta `<Source>/`). Os arquivos individuais usam nomes
da tabela canônica (singular: `conversations`, `messages`, etc).

---

## 6. Fases de implementação

### Fase 2a (mínima): schema atualizado + parser básico

**Objetivo:** parser v3 funcional cobrindo features simples (não Branch
ainda). AI Interaction Analysis pode consumir parquets minimamente úteis.

- Atualizar `src/schema/models.py`:
  - +4 campos em Conversation
  - +8 campos em Message (incluindo `branch_id` com default fixo)
  - +1 campo em ToolEvent
  - **NÃO adicionar Branch ainda** (deixa pra Fase 2b)
- Criar `src/parsers/chatgpt_v3.py`:
  - Herda `_extract_text` de v2
  - Implementa: voice (4.2), DALL-E (4.3), Custom GPT (4.7), tools (4.8)
  - branch_id = `<conv>_main` constante (sem branches reais ainda)
  - Tether quote, Canvas, Deep Research **viram ToolEvents** (já funciona
    sem Branch)
- Criar `scripts/chatgpt-parse.py`
- Adicionar `pyarrow>=14.0` ao `requirements.txt`
- Escrever `tests/parsers/test_chatgpt_v3.py` com 5+ testes (1 por
  fixture exceto branches)

**Critério de pronto:**
- ✅ `python scripts/chatgpt-parse.py` gera 4 parquets sem erro
- ✅ Schema canônico respeitado (testes validam)
- ✅ Idempotente
- ✅ 5+ testes do parser passing
- ✅ AI Interaction Analysis pode `pd.read_parquet()` os 4 outputs

### Fase 2b (Branches): tabela própria + walking completo

**Objetivo:** preservar branches off-path.

- Adicionar dataclass `Branch` em `src/schema/models.py`
- Adicionar dataframe builder `branches_to_df()` (espelhar conversations_to_df)
- Atualizar `chatgpt_v3.py`:
  - Implementar `_extract_branches(conv)` — varre mapping completo
  - `_extract_messages` recebe branches já resolvidas, atribui `branch_id`
- Adicionar testes específicos de branches (fixture `raw_with_branches.json`)

**Critério de pronto:**
- ✅ `branches.parquet` gerado
- ✅ Conv sem fork: 1 branch ("main"), todas msgs nela
- ✅ Conv com fork: N branches, msgs distribuídas corretamente
- ✅ `is_active` corretamente marca branch contendo `current_node`

### Fase 2c (validação cruzada): paridade com v2

**Objetivo:** validar que v3 cobre tudo que v2 cobria + mais.

- Rodar v2 e v3 no mesmo merged
- Comparar:
  - Mesmas convs em ambos? (deve ser igual)
  - Msgs do v3 ⊇ msgs do v2 (v3 pode ter mais por causa de branches)
  - Tool events só no v3 (v2 não gera)
- Documentar diferenças em `docs/parser-v3/validation.md`

**Critério de pronto:**
- ✅ Diff documentado
- ✅ Sem regressões (tudo que v2 tinha, v3 também tem)
- ✅ Aprovação humana antes de promover v3 a `chatgpt`

### Fase 2d (promoção): v3 vira `chatgpt`

**Objetivo:** v3 é o único parser ativo, v1/v2 deprecated.

- `source_name = "chatgpt"` em v3
- Renomear arquivo: `chatgpt_v3.py` → `chatgpt_v2.py` (substituindo)
  ou manter `chatgpt_v3.py` e deprecar via warning em `chatgpt_v2.py`
- Atualizar `VALID_SOURCES` em models.py se necessário
- Outros consumidores (dashboard, AI Interaction Analysis) usam
  `source == "chatgpt"`

**Critério de pronto:**
- ✅ AI Interaction Analysis aponta pra novo path/source
- ✅ Dashboard reflete dados v3
- ✅ Documentação atualizada

---

## 7. Plan de testes

### 7.1. Suite de fixtures (já existente)

```
tests/extractors/chatgpt/fixtures/
├── raw_with_branches.json          # 5 nodes, ≥1 fork
├── raw_with_voice.json             # 14 nodes, audio_transcription
├── raw_with_dalle.json             # 8 nodes, image_asset_pointer
├── raw_with_canvas.json            # 11 nodes, canmore.*
├── raw_with_deep_research.json     # 7 nodes, model_slug research
├── raw_with_tether_quote.json      # 8 nodes, content_type tether_quote
├── raw_with_custom_gpt.json        # 12 nodes, gizmo_id g-*
├── raw_with_tools.json             # 5 nodes, author.role=tool
└── test_fixtures_integrity.py     # 24 meta-tests (sanity)
```

### 7.2. Testes do parser (novos)

`tests/parsers/test_chatgpt_v3.py`:

- `test_parse_voice_extracts_transcript_and_direction`
- `test_parse_dalle_resolves_asset_path`
- `test_parse_canvas_creates_tool_events`
- `test_parse_deep_research_creates_tool_events`
- `test_parse_tether_quote_creates_tool_event`  (não Message)
- `test_parse_custom_gpt_distinguishes_from_project`
- `test_parse_tools_creates_tool_events_with_correct_event_type`
- `test_parse_branches_creates_branch_table` (Fase 2b)
- `test_parse_main_branch_is_default_for_no_fork`
- `test_parse_idempotent_two_runs_same_output`
- `test_parse_full_merged_does_not_crash` (smoke test no merged real)

### 7.3. Testes de schema

`tests/schema/test_models.py` (existentes — não devem quebrar):
- Adicionar testes pra Branch
- Validar que Conversation/Message com novos campos serializam corretos

---

## 8. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Schema breaking change pra outros parsers | Campos novos são Optional[] ou têm default — outros parsers continuam funcionando, só não preenchem |
| Pyarrow ausente em terceiros | Adicionar como dep firme (não opcional) em requirements.txt |
| Asset paths não resolvíveis (file não existe no disco) | Fallback: setar `None` em asset_paths, logar warning, não crashar |
| Custom GPT deletado sem fixture | Implementar com heurística "se gizmo_name não resolvível, gizmo_resolved=False" — validar quando aparecer empiricamente |
| Branches com loops (parent ciclo) | v2 já tem proteção (`seen` set) — manter em v3 |
| multimodal_text shape variável | Tratar parts mistas (str + dict) com extração robusta — testar com fixture específica se necessário criar |
| Tool name opaco (códigos hash) | `event_type = "other"` é fallback OK — JIT plugins não precisam de mapping específico |
| Performance em conv grande (>500 msgs) | Profile antes de otimizar; tree-walk é O(n), aceitável até 10k nodes |

---

## 9. O que NÃO é objetivo

- ❌ Análise interpretativa de conteúdo (sentiment, topics, etc)
- ❌ Re-extração de assets (sync já fez)
- ❌ Conversão pra outros formatos (CSV, JSON ad-hoc)
- ❌ UI ou interface (parser é CLI puro)
- ❌ Multi-thread / async (1 conv por vez é OK; 1171 convs em <30s)
- ❌ Streaming output (lê tudo, escreve tudo — parquet é otimizado pra batch)
- ❌ Tratamento de v1 (legacy GPT2Claude) — fica deprecated, não migrado

---

## 10. Critérios de pronto (geral)

- ✅ `python scripts/chatgpt-parse.py` gera os 5 parquets sem erro no
  merged real (1171 convs hoje)
- ✅ Cada uma das 8 features tem teste passando
- ✅ Schema canônico atualizado, testes existentes não quebram
- ✅ Idempotente (rodar 2x = bytes idênticos no parquet)
- ✅ AI Interaction Analysis consegue carregar e analisar os parquets
- ✅ Dashboard descritivo (Quarto) consegue ler e renderizar
- ✅ Documentação atualizada (CLAUDE.md, README, glossary)

---

## 11. Sequência sugerida pra implementador

1. **Ler `parser-v3-empirical-findings.md`** — contexto fundamental
2. **Ler `src/parsers/chatgpt_v2.py`** — código base que vai herdar
3. **Ler `src/schema/models.py`** — schema atual a estender
4. **Rodar fixtures meta-tests** pra confirmar ambiente OK:
   ```bash
   PYTHONPATH=. .venv/bin/pytest tests/extractors/chatgpt/fixtures/ -v
   ```
5. **Implementar Fase 2a** (schema + parser básico sem branches)
6. **Validar empiricamente:**
   ```bash
   PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py
   # inspecionar data/processed/ChatGPT/*.parquet com pandas
   ```
7. **Implementar Fase 2b** (branches)
8. **Implementar Fase 2c** (validação cruzada com v2)
9. **Aguardar OK humano antes de Fase 2d** (promoção)

---

## 12. Notas finais

### Adições potenciais (futuro, não bloqueante)

- Tabela `MessageAsset` separada se asset_paths virar gargalo (>3
  paths/msg consistentemente)
- Validação cruzada entre msg.metadata.gizmo_id e conv.gizmo_id
- Suporte a `content_type=multimodal_text` com parts mistas (provável
  precisar fixture nova)
- Tratamento de `weight=0` como hidden_reason (já documentado, validar)
- Detecção de mode automaticamente (chat / search / research / dalle /
  copilot) baseado em metadata + content_types

### Validações que aparecem com mais dados

- Custom GPT deletado (gerar fixture quando rolar empiricamente)
- `content_filter` em finish_reason (não observado, mas reportado pela API)
- Estrutura completa de `multimodal_text` em casos com >3 parts

### Independência das fases do dashboard

Parser v3 é **independente** do dashboard:
- Fase 1 do dashboard (Streamlit MVP, sem parser) já está implementada
- Parser v3 desbloqueia Fase 3 do dashboard (Quarto descritivo)
- Mas Fase 1 do dashboard não depende do parser

Pode implementar em qualquer ordem.

### Stats vão divergir entre Fase 1 e Fase 3 do dashboard (esperado)

O dashboard Fase 1 (Streamlit, já em produção) calcula stats via
**heurísticas leves** direto do `chatgpt_merged.json`:

- `total_messages_estimated`: conta nodes com `message != null` (não
  filtra hidden, system bridges, tool calls)
- `models`: pega qualquer `model_slug` em qualquer msg (inclui
  `model_editable_context` e outros system slugs)
- `convs_per_project`: groupby `_project_id` direto

O parser v3 (Fase 2) gera contagens **exatas** filtrando role∈{user,
assistant}, excluindo hidden/preserved/system. Quando Fase 3 estiver
ativa (Quarto consumindo parquets), as stats vão **divergir** das do
dashboard Fase 1 — esperado, mais fiéis.

**Migração futura (não bloqueante):** quando Fase 3 estabilizar, dashboard
Fase 1 pode ser refatorado pra ler dos parquets ao invés do merged.json.
Stats ficam consistentes em todo o produto. Mas Fase 1 funciona standalone
sem essa migração.

### Compatibilidade com o dashboard Fase 1

Campos que o dashboard Fase 1 lê do `chatgpt_merged.json` e que devem
permanecer disponíveis (no merged, não no parquet):

| Campo no raw/merged | Quem consome |
|---|---|
| `_last_seen_in_server` | Dashboard (active vs preserved) |
| `_archived` ou `is_archived` | Dashboard (archived count) |
| `_project_id` | Dashboard (groupby project) |
| `_project_name` | Dashboard (label projects) |
| `mapping` (estrutura) | Dashboard (count msgs estimado) |
| `metadata.model_slug` | Dashboard (count modelos) |

O parser v3 **não modifica o merged.json** — só lê. Esses campos
continuam intactos pra dashboard Fase 1 funcionar. Parser apenas gera
representação canônica derivada (parquets) que dashboard Fase 3 lê
adicionalmente.
