# NotebookLM probe findings — 2026-05-02

Empirical findings descobertos durante a migração + smoke + full sync de
NotebookLM. Esquema posicional Google batchexecute.

## Volumes (smoke=5 conta 1, em validação para full)

| Tabela | Smoke 5nb conta 1 | Full target (a confirmar) |
|---|---|---|
| conversations | 5 | ~95 (acc1) + ~? (acc2) |
| messages | 5 (system summaries) | ~190 + chat extras |
| sources | 21 | ~1500-2000 |
| outputs | 30 (audio+blog+video+data table+slide+mind_map) | maior |
| notes | 8 | proporcional |
| guide_questions | 15 (~3/notebook) | ~570 |
| branches | 5 (sempre `<conv>_main`) | ~190 |
| tool_events | 0 | depende de chat populado |

## Schema posicional descoberto

### Notebook listing (RPC wXbhsf)

```
nb[0] = title (str)
nb[2] = uuid (str)
nb[3] = emoji (str)
nb[5] = attrs (list)
  nb[5][5] = update_time [epoch_secs, nanos]
  nb[5][8] = create_time [epoch_secs, nanos]
```

### Notebook metadata (RPC rLM1Ne)

```
metadata[0] = [title, sources_list, ...]
sources_list[i] = [[uuid], filename, [meta], [tags]]
  meta[1] = size_bytes (int)
  meta[2] = create_time [epoch_secs, nanos]
```

### Guide (RPC VfAZjd)

```
guide[0] = [[summary_str], [[questions]], None, None, None, ...]
questions[i] = [question_text, full_prompt]
```

Em todos os notebooks observados: summary populado + questions (~3 por notebook).

### Chat (RPC khqZz)

**76% dos notebooks no legacy do projeto pai retornam chat=None** —
chat só populado quando user interage com o assistente. Smoke não capturou
nenhum chat populado, schema dos turns ainda **não mapeado** empiricamente.

Workaround: parser v3 cria 1 system message por notebook a partir do
`guide.summary` pra garantir `message_count >= 1`.

**TODO:** quando chat populado for capturado, mapear schema posicional dos
turns (provavel: `chat[?] = list of turns, turn[?] = role/content/timestamp`).

### Notes (RPC cFji9)

```
notes[0] = [list of items, ...]
notes[1] = [epoch_secs, nanos]  (timestamp)

item[0] = uuid (str)
item[1] = [uuid, content_or_uuid_ref, [...], ...]
  item[1][0] = uuid (repeated)
  item[1][1] = content_str (notes/briefs reais) OR mind_map_uuid (refs)
```

Heurística no parser:
- Se `item[1][1]` for UUID 36-char (mind_map ref): skip (não é note real)
- Se for content longo: registrar como note (kind = `brief` se começa com
  `Com base`/`Based`/`**`/`#`, senão `note`)

### Artifacts list (RPC gArtLc)

```
artifacts[0] = [list of items]
item = [uuid, title, type_int, source_refs_lists, status_str, ...]

source_refs_lists[i] = [[source_uuid]]
status: "ARTIFACT_STATUS_READY" | "ARTIFACT_STATUS_PENDING" | etc

types observados:
  1 = Audio Overview     (URL direta — download_asset)
  2 = Blog/Report        (texto via v9rmvd)
  3 = Video Overview     (URL direta)
  4 = Flashcards/Quiz    (JSON via v9rmvd)
  7 = Data Table         (JSON via v9rmvd)
  8 = Slide Deck         (PDF+PPTX URLs)
  9 = Infographic        (JSON via v9rmvd)
```

### Artifact individual (RPC v9rmvd, types 2/4/7/9)

Schema observado **para type=2 (Blog)**:

```
artifact[0][0] = [uuid, title, type, source_refs, status,
                  None, None, [content_md_str]]
content em [0][0][7][0]
```

Schema dos types 4/7/9 ainda **não validado empiricamente** (smoke não
capturou). Parser v3 usa fallback `json.dumps(raw)` se schema diferente.

**TODO empirical:** capturar amostras dos types 4/7/9 e refinar
`extract_artifact_content`.

### Mind map UUID (RPC hPTbtc)

```
mind_map[0] = [[mind_map_uuid_str]]
acessar via: mind_map[0][0][0]
```

### Mind map tree (RPC CYK0Xb) — payload corrigido empiricamente

```
Payload: [notebook_uuid, mind_map_uuid]   ← descoberto via probe 2026-05-02
(ANTES o api_client tinha [mind_map_uuid] que retornava None silenciosamente)

Response: [[node_uuid, mind_map_uuid, [0, "version_id", [ts]], None, ""]]
```

**Schema observado retorna SO METADATA do mind_map**, não a árvore de nodes
+ children. Provavelmente há outro RPC pra fetchar a tree completa.
Parser v3 serializa o que tem (json.dumps).

**TODO empirical:** investigar se há RPC adicional pra tree de nodes
(probe Chrome MCP clicando no mind_map na UI).

### Source content (RPC hizoJc)

```
source[0] = [[uuids], filename, [meta], [tags/flags]]
source[3][0] = [list of chunks]

chunk = [start_offset, end_offset, [[[start, end, [text_str]]]]]
```

Texto extraido em `chunk[2][0][0][2][0]`. Concatenando todos os chunks
recupera content completo do source.

## Bugs descobertos+fixados durante migração

### 1. CYK0Xb payload errado (api_client.py)

`fetch_mind_map_tree` retornava None silenciosamente. Payload era
`[mind_map_uuid]` quando o servidor exige `[notebook_uuid, mind_map_uuid]`.
Probe via batchexecute direto descobriu o payload correto.

### 2. Mind map UUID extraction wrong source (fetcher.py)

`_extract_mind_map_uuid` lia de `nb_data["notes"]` (RPC cFji9) mas o UUID
está em `nb_data["mind_map"]` (RPC hPTbtc). Dois RPCs distintos —
fetcher legacy capturava ambos mas extraction misturou.

### 5 bugs preventivos aplicados desde primeiro commit

(Padrão das 6 plataformas anteriores — não esperar review pegar:)

1. `_get_max_known_discovery(output_dir)` — não `parent`
2. `discover()` lazy persist — separa de `persist_discovery()`
3. `--full` propagado pro reconcile no sync script
4. (N/A pra NotebookLM) `fetch_conversations(skip_existing=False)`
5. Pasta única per-account `data/raw/NotebookLM/account-{N}/`

## Out of scope (cortado durante brainstorm)

- ❌ Probe Chrome MCP de RPCs novos durante CRUD UI (cobertura ja é ótima)
- ❌ Featured/Explore (RPC ub2Bae) — não são do user
- ❌ Versionamento histórico de outputs (não exposto pelo NotebookLM)
- ❌ Reimport de `more.design` (profile perdido — raw preservado no pai)

## Validação cruzada vs legacy do projeto pai

Pai (`~/Desktop/AI Interaction Analysis/data/processed/`) tem 4 parquets
legacy v1. v3 ⊇ legacy estritamente:

| Tabela | Pai (v1) | v3 |
|---|---|---|
| conversations | 149 rows, schema v1 | + schema v3 fields, multi-account namespace |
| messages | 114 rows | + guide.summary como system msg garantindo `count >= 1` |
| sources | 1306 rows (só nomes) | + content extraído full, content_size, token_count |
| guides | 144 rows (só summary) | summary movido pra `Conversation.summary` + tabela `guide_questions` separada |
| notes | ❌ ausente | ✅ tabela auxiliar nova (`kind` ∈ {note, brief}) |
| outputs | ❌ ausente | ✅ tabela com 9 tipos + asset_paths + content |
| tool_events | ❌ ausente | ✅ canônico (vazio se chat sem tools) |
| branches | ❌ ausente | ✅ canônico (`<conv>_main` sempre) |

## Comportamento do servidor (a validar bateria CRUD UI)

- Rename de notebook: `update_time` bumpa? (provavel: sim, igual outras plataformas)
- Delete: `is_preserved_missing=True`? `last_seen_in_server` preservado? (provavel: sim)
- Pin/star: NotebookLM tem essa feature? (descobrir na UI — provavel: não)
- Add source: reflete em sources.parquet? `update_time` bumpa?

Documentar resultados em `docs/notebooklm-server-behavior.md` após bateria.
