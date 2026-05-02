# NotebookLM Schema v3 — Design

**Data:** 2026-05-02
**Plataforma:** NotebookLM (7/7 — última do backlog)
**Tipo:** spec de schema + escopo de captura + escopo de migração

---

## 1. Contexto

NotebookLM eh a ultima plataforma a ser shipped no projeto. As 6 anteriores
(ChatGPT, Claude.ai, Perplexity, Qwen, DeepSeek, Gemini) seguem o playbook
ChatGPT — pasta unica cumulativa + sync orquestrador + parser v3 + Quarto
descritivo + bateria CRUD UI.

NotebookLM eh **a mais complexa** porque nao eh chat puro: cada notebook eh
um workspace que gera 9 tipos de outputs distintos (audio overview, blog
post, video overview, flashcards/quiz, data table, slide deck PDF+PPTX,
infographic, mind map). Schema canonico (Conversation/Message/ToolEvent/
Branch) **nao encaixa direto**. Decisao tomada via brainstorm: **maximizar
canonico + 4 tabelas auxiliares dedicadas**.

## 2. Estado atual (legacy)

### Modulos extractor (`src/extractors/notebooklm/`)
- `auth.py` — VALID_ACCOUNTS = ("hello", "marloon"); ACCOUNT_LANG mapeia conta→hl
- `api_client.py` — wraps batchexecute; mapeia 11 RPCs
- `batchexecute.py` — Google batchexecute helper (igual Gemini)
- `discovery.py` — lista notebooks via wXbhsf
- `fetcher.py` — chama 6 RPCs por notebook + sources
- `asset_downloader.py` — baixa binarios (audio, video, slide deck, source PDFs)
- `orchestrator.py` — `run_export()` smoke-friendly, lite-fetch incremental

### Reconciler + parser
- `src/reconcilers/notebooklm.py` — preservation legacy
- `src/parsers/notebooklm.py` — outdated (provavel rewrite total, igual DeepSeek/Gemini)

### Scripts
- `notebooklm-export.py`, `notebooklm-login.py`, `notebooklm-reconcile.py`,
  `notebooklm-download-assets.py`, `notebooklm-download.py`, `notebooklm-poc.py`
- 6 probes: audio, generators, mindmap, rpcids, source, source-v2

### Profiles disponiveis (do projeto pai)
- `notebooklm-profile-hello` (61MB)
- `notebooklm-profile-marloon` (29MB)
- `more.design` raw preservado mas profile foi perdido

### Smoke 2026-05-02 (validado)
- 95 notebooks na conta hello (todos descobertos)
- 5 notebooks fetched: 21 sources, 25 RPCs ok, 0 erros
- Pasta legacy: `data/raw/NotebookLM Data/hello.marlonlemes/2026-05-02T10-40/`
- Tipos de artifact vistos: 1 (audio), 2 (blog), 3 (video), 7 (data table),
  8 (slide deck) — confirmando feature mix real

## 3. RPCs do NotebookLM (mapeados em `api_client.py`)

| RPC ID | Funcao | Captura legacy? |
|---|---|---|
| `wXbhsf` | List notebooks (My Notebooks) | ✅ |
| `ub2Bae` | List featured (Explore) | ❌ — fora do escopo |
| `rLM1Ne` | Notebook metadata + sources list | ✅ |
| `VfAZjd` | Guide (summary + perguntas sugeridas) | ✅ |
| `khqZz` | Chat history | ✅ |
| `cFji9` | Notes + briefs + mind_map UUID | ✅ |
| `gArtLc` | Artifacts list (TODOS 9 tipos) | ✅ (mas mal nomeado como `audios`) |
| `v9rmvd` | **Fetch artifact content** (tipos 2/4/7/9) | ❌ **gap a fechar** |
| `CYK0Xb` | **Mind map tree fetch** | ❌ **gap a fechar** |
| `hPTbtc` | Mind map UUID legacy | ✅ (substitui por cFji9) |
| `hizoJc` | Source content extraido | ✅ |

Tipos de artifact (gArtLc):
- 1 = Audio Overview (URL direta — download_asset)
- 2 = Blog/Report (texto via v9rmvd) ⚠
- 3 = Video Overview (URL direta — download_asset)
- 4 = Flashcards/Quiz (JSON via v9rmvd) ⚠
- 7 = Data Table (JSON via v9rmvd) ⚠
- 8 = Slide Deck (PDF+PPTX URLs)
- 9 = Infographic (JSON via v9rmvd) ⚠

⚠ Sem `v9rmvd`, conteudo dos tipos 2/4/7/9 fica perdido. Spec define captura
desse RPC como **obrigatoria**.

## 4. Decisoes fundamentais (alinhadas via brainstorm)

### 4.1. Schema mapping — maximizar canonico + 4 auxiliares dedicadas

**Princípio:** "normalizar no maximo que os dados possibilitem, e o resto
trata com tabelas especificas, sem crise" (user, 2026-05-02).

- **4 parquets canonicos** (Conversation, Message, ToolEvent, Branch) —
  garantem link com queries cross-plataforma do dashboard
- **4 parquets auxiliares NotebookLM-specific** (sources, notes, outputs,
  guide_questions) — semantica dedicada sem hack
- **Total: 8 parquets**

### 4.2. Multi-conta — normalizar pra `account-{1,2}` (igual Gemini)

- account-1 = profile original `hello`
- account-2 = profile original `marloon`
- `more.design` perdido (raw preservado, profile nao recuperavel)
- Profile path: `.storage/notebooklm-profile-{1,2}/`
- Pasta unica per-account: `data/raw/NotebookLM/account-{N}/` e
  `data/merged/NotebookLM/account-{N}/`
- `auth.py` refatorado (VALID_ACCOUNTS, ACCOUNT_LANG)

### 4.3. Escopo de captura — "pegar tudo possivel"

**Incluir** (gaps a fechar):
- ✅ `fetch_artifact` (v9rmvd) per artifact_uuid — conteudo de tipos 2/4/7/9
- ✅ `fetch_mind_map_tree` (CYK0Xb) — arvore completa do mind map
- ✅ Asset binarios (download_asset ja faz): audio MP4, video MP4,
  slide deck PDF+PPTX, source PDFs/imagens
- ✅ Source content extraido (hizoJc — ja capturado)

**Excluir** (cortado pelo user):
- ❌ Probe Chrome MCP de RPCs novos durante CRUD UI (cobertura ja eh otima
  com sources + chats + 9 tipos de mídia gerada)
- ❌ Featured/Explore lists (ub2Bae) — nao sao do user
- ❌ Versionamento de outputs (NotebookLM nao expoe historico de gerações
  anteriores; so o output atual)

### 4.4. Bateria CRUD UI minima

Antes de declarar shipped (regra dura do projeto):
- ✅ Rename de notebook → `update_time` bumpa? Title bate em parquet?
- ✅ Delete de notebook → `is_preserved_missing=True`?
- ✅ Descobrir se NotebookLM tem pin/star (provavel: nao expoe na UI atual)
- ✅ Add/remove source → reflete em `notebooklm_sources.parquet`?

## 5. Schema canonico (4 parquets)

### 5.1. `notebooklm_conversations.parquet` (1 row por notebook)

Reusa dataclass `Conversation` ja existente em `src/schema/models.py`:

| Campo | Valor pra NotebookLM |
|---|---|
| `conversation_id` | `account-{N}_{notebook_uuid}` (namespace, igual Gemini) |
| `source` | `'notebooklm'` (ja em VALID_SOURCES) |
| `account` | `'1'` ou `'2'` |
| `title` | notebook title |
| `created_at` | de `nb[5][8]` (epoch) |
| `updated_at` | de `nb[5][5]` (epoch) |
| `message_count` | total de chat turns |
| `model` | `'gemini'` (placeholder; refinar se descobrirmos versao) |
| `mode` | `'chat'` (mais proximo dos VALID_MODES atuais; **decisao secundaria**: avaliar adicionar `'notebook'` em VALID_MODES) |
| `summary` | `guide.summary` (campo ja existe — Claude.ai usa) |
| `is_pinned` | `None` ate descobrir na bateria CRUD |
| `is_preserved_missing`, `last_seen_in_server` | preservation pattern |
| `url` | `https://notebooklm.google.com/notebook/{uuid}` |

Demais campos (project_id, gizmo_*, is_archived, is_temporary, settings_json,
citations_json, etc) ficam `None`/default.

### 5.2. `notebooklm_messages.parquet` (chat turns apenas)

Reusa dataclass `Message`:

| Campo | Valor |
|---|---|
| `message_id` | UUID extraido do chat raw |
| `conversation_id` | `account-{N}_{notebook_uuid}` |
| `role` | `'user'` ou `'assistant'` |
| `content` | texto da msg |
| `created_at` | timestamp do turn |
| `branch_id` | `<conv>_main` (default) |
| `account` | `'1'` ou `'2'` |
| `model` | `'gemini'` |

**NotebookLM tem chat?** RPC khqZz existe; smoke (5 notebooks) retornou
`chat: None` em todos. Provavel: chat so populado quando user interage.
Empirical findings vao confirmar.

### 5.3. `notebooklm_tool_events.parquet`

Reusa dataclass `ToolEvent`. Populada se chat tiver:
- Citations (links pra sources usados na resposta)
- Search/research interno (se NotebookLM expoe)
- Deep dive nos sources

Tabela pode ficar **vazia inicialmente** ate descobrirmos com chat real.
Sem problema — schema canonico aceita zero linhas.

### 5.4. `notebooklm_branches.parquet`

Reusa dataclass `Branch`. NotebookLM **nao tem fork** (chat eh linear).

- 1 row por conv: `<conv>_main`, `is_active=True`, `parent_branch_id=None`

## 6. Tabelas auxiliares (4 parquets)

### 6.1. `notebooklm_sources.parquet` (PDFs/links uploaded por notebook)

**Reusa `ProjectDoc`** ja existente (precedent: Claude.ai usa pra
`claude_ai_project_docs.parquet`). Mapeamento:

| Campo `ProjectDoc` | Valor NotebookLM |
|---|---|
| `doc_id` | source_uuid |
| `project_id` | `account-{N}_{notebook_uuid}` |
| `source` | `'notebooklm'` |
| `file_name` | filename do source |
| `content` | texto extraido do hizoJc raw |
| `content_size` | bytes do content |
| `estimated_token_count` | content_size // 4 (heuristica padrao) |
| `created_at` | timestamp se disponivel |

Notebook → sources eh 1:N. `project_id` aqui aponta pra
`Conversation.conversation_id` (mapeamento conv→sources).

### 6.2. `notebooklm_notes.parquet` (notas + briefs gerados)

**Novo dataclass** `NotebookLMNote` em `src/schema/models.py`:

```python
@dataclass
class NotebookLMNote:
    note_id: str
    conversation_id: str  # account-{N}_{notebook_uuid}
    source: str           # 'notebooklm'
    account: str          # '1' ou '2'
    title: Optional[str]
    content: str
    kind: str             # 'note' | 'brief'
    source_refs_json: Optional[str]  # JSON list de source_uuids referenciados
    created_at: Optional[pd.Timestamp]
```

Notes vem do RPC cFji9. Briefs sao gerados automaticamente pelo NotebookLM
em resposta as perguntas do guide; notes sao escritas pelo user OU geradas
em resposta a um prompt manual.

### 6.3. `notebooklm_outputs.parquet` (9 tipos de outputs gerativos)

**Novo dataclass** `NotebookLMOutput`:

```python
@dataclass
class NotebookLMOutput:
    output_id: str
    conversation_id: str
    source: str
    account: str
    output_type: int       # 1, 2, 3, 4, 7, 8, 9 (artifact types) + 10 (mind_map)
    output_type_name: str  # 'audio_overview', 'blog_post', 'video_overview',
                           # 'flashcards_quiz', 'data_table', 'slide_deck',
                           # 'infographic', 'mind_map'
    title: Optional[str]
    status: Optional[str]  # ARTIFACT_STATUS_* (READY, PENDING, etc)
    asset_path: Optional[list[str]]  # pra binarios (audio/video/slide PDF/PPTX)
    content: Optional[str]           # pra texto/JSON (blog, flashcards, quiz,
                                     # data_table, infographic, mind_map tree)
    source_refs_json: Optional[str]  # JSON list dos source_uuids usados
    created_at: Optional[pd.Timestamp]
```

**Type 8 (slide deck)** tem 2 binarios (PDF + PPTX) — `asset_path` eh lista.
**Type 10 (mind_map)** sai do RPC CYK0Xb — `content` guarda o tree JSON.

### 6.4. `notebooklm_guide_questions.parquet` (perguntas sugeridas pelo guide)

**Novo dataclass** `NotebookLMGuideQuestion`:

```python
@dataclass
class NotebookLMGuideQuestion:
    question_id: str       # hash(notebook_uuid + order)
    conversation_id: str
    source: str
    account: str
    question_text: str
    full_prompt: str       # texto completo do prompt sugerido
    order: int             # sequencia na lista (0-indexed)
```

Perguntas vem do guide (RPC VfAZjd) — sao templates sugeridos pra user
explorar o conteudo. Nao sao chat messages.

## 7. Mudancas no extractor

### 7.1. Refactor `auth.py`

- `VALID_ACCOUNTS = ("1", "2")`
- `ACCOUNT_LANG = {"1": "en", "2": "pt-BR"}`
- `get_profile_dir(account: str) -> Path("notebooklm-profile-{account}")`

### 7.2. Refactor `orchestrator.py` (espelhando Gemini)

- Pasta unica: `data/raw/NotebookLM/account-{N}/` (sem timestamps)
- `_find_last_capture` removido (nao precisa — pasta eh sempre a mesma)
- `_get_max_known_discovery(output_dir)` — **NAO** `parent` (bug preventivo #1)
- `discover()` separado de `persist_discovery()` — lazy persist (bug #2)
- `LAST_CAPTURE.md` regenerado a cada run
- `capture_log.jsonl` append-only (substitui capture_log.json)

### 7.3. Adicionar fetcher de artifacts individuais

Em `fetcher.py`:
- Apos `fetch_artifacts` listar, iterar artifact_uuids dos tipos 2/4/7/9 e
  chamar `fetch_artifact` (v9rmvd)
- Salvar em `notebooks/{nb_uuid}_artifacts/{artifact_uuid}.json`
- Pra mind_map: chamar `fetch_mind_map_tree` (CYK0Xb) com mind_map_uuid
  (vindo do cFji9 raw) e salvar em `notebooks/{nb_uuid}_mind_map_tree.json`

### 7.4. Asset download (download_asset)

Asset downloader ja existe; adicionar:
- Skip-existing por asset_path
- Atualizar `assets_manifest.json` per-account
- Cobrir audio (mp4), video (mp4), slide deck (PDF + PPTX),
  source binarios (PDF), source page images

## 8. Mudancas no reconciler

`src/reconcilers/notebooklm.py`:
- Pasta unica: `data/merged/NotebookLM/account-{N}/`
- `FEATURES_VERSION = 2` (incrementa)
- Preservation completa (preserved_missing por notebook)
- `LAST_RECONCILE.md` per-account
- `reconcile_log.jsonl` per-account append-only
- `notebooklm_merged_summary.json` per-account
- Bug preventivo #3: `--full` propagado (sync passa flag explicito)
- Bug preventivo #4: `fetch_conversations(skip_existing=False)` quando
  orchestrator filtrou (nao se aplica diretamente — NotebookLM ja sempre
  refetch tudo conforme nota no orchestrator legacy; manter caminho atual)

## 9. Sync orquestrador

`scripts/notebooklm-sync.py` (novo) — espelha `gemini-sync.py`:

3 etapas (per-account, iteradas em sequencia):
1. **Capture** — `run_export(account)` (orchestrator)
2. **Asset download** — `download_assets(account)` (binarios)
3. **Reconcile** — `run_reconciliation(account, full=args.full)`

Flags:
- `--account 1|2|all` (default: all — itera ambas)
- `--full` (propagado pro reconciler — bug #3)
- `--no-binaries` (pula etapa 2)
- `--no-reconcile` (pula etapa 3)
- `--dry-run`

## 10. Parser v3

`src/parsers/notebooklm.py` — rewrite total. Helpers em
`src/parsers/_notebooklm_helpers.py`:
- `_parse_metadata(raw)` — extrai title, sources_list de rLM1Ne
- `_parse_guide(raw)` — extrai summary + questions de VfAZjd
- `_parse_chat(raw)` — extrai chat turns de khqZz (provavel: schema
  posicional, requer probe quando chat estiver populado)
- `_parse_notes(raw)` — extrai notes/briefs de cFji9
- `_parse_artifacts(raw, individual_artifacts)` — combina lista (gArtLc)
  com conteudo individual (v9rmvd) por artifact_uuid
- `_parse_mind_map(uuid_raw, tree_raw)` — extrai estrutura tree de CYK0Xb
- `_parse_source_content(raw)` — extrai texto de hizoJc

Saida: 8 parquets em `data/processed/NotebookLM/`. Idempotente.

Backup do legacy em `_backup-temp/parser-notebooklm-promocao-2026-05-02/`.

## 11. Quarto descritivo

3 documentos (igual Gemini multi-conta):
- `notebooks/notebooklm.qmd` — consolidado, stacked bars per-account
- `notebooks/notebooklm-acc-1.qmd` — template canonico, account-1 only
- `notebooks/notebooklm-acc-2.qmd` — template canonico, account-2 only

Cor primaria: **laranja Google `#F4B400`** (distinta das 6 ja usadas)

Secoes:
1. Dados disponiveis (counts dos 8 parquets)
2. Cobertura (% notebooks com cada tipo de artifact)
3. Volumes (top notebooks por tamanho/atividade)
4. **9 tipos de outputs** (distribuicao + amostras)
5. Sources (volume + extensoes + binarios)
6. Preservation (notebooks deletados)

Render < 30s. HTML self-contained < 100MB.

## 12. Bateria CRUD UI

Documentar em `docs/notebooklm-server-behavior.md`:
- Rename de notebook: `update_time` bumpa? Title bate?
- Delete de notebook: preserved_missing? `last_seen` preservado?
- Pin/star: NotebookLM tem essa feature? (provavel nao — UI atual nao expoe)
- Add source: reflete em sources.parquet? `update_time` bumpa?
- Remove source: preserved_missing por source? Texto preservado?
- Generate output novo (audio/blog/etc): captura na proxima run?
- Delete output: preserved? sumido?

## 13. Bugs preventivos (lições caras das 6 plataformas anteriores)

Aplicar **desde o primeiro commit** — nao esperar review pegar:

1. **`_get_max_known_discovery(output_dir)`** — nao `parent` (vaza entre
   plataformas via rglob)
2. **`discover()` lazy persist** — separar de `persist_discovery()` chamado
   pelo orchestrator APOS fail-fast
3. **`--full` propagado** no sync script
4. **`fetch_conversations(skip_existing=False)`** quando orchestrator
   filtrou — N/A pra NotebookLM (sempre refetch), manter pattern atual
5. **Pasta unica per-account** — `data/raw/NotebookLM/account-{N}/`,
   namespace `account-{N}_{uuid}` em `conversation_id`, dashboard ja agrega
6. **Discovery flag (pin/starred)** capturada no listing E detectada como
   signal de update no reconciler — N/A se NotebookLM nao tiver pin

## 14. Criterios de pronto (shipped)

- [ ] 4 parquets canonicos populados
- [ ] 4 parquets auxiliares populados
- [ ] Sync 3 etapas idempotente
- [ ] Pasta unica multi-conta `data/raw/NotebookLM/account-{N}/`
- [ ] `LAST_CAPTURE.md` + `LAST_RECONCILE.md` + jsonls per-account
- [ ] CRUD UI core validado (rename + delete + pin descoberto)
- [ ] Quarto rendiriza < 30s, HTML < 100MB
- [ ] Dashboard reflete automaticamente (KNOWN_PLATFORMS ja inclui notebooklm)
- [ ] CLAUDE.md atualizado (tabela §1 + bloco "Estado validado")
- [ ] Empirical findings doc (`docs/notebooklm-probe-findings-2026-05-XX.md`)
- [ ] Server behavior doc (`docs/notebooklm-server-behavior.md`)
- [ ] Tests parser-specific cobrindo 8 parquets
- [ ] Review cruzado (`project-hardening` fase 5+6): zero achados
- [ ] Suite total >= 320 + N parser tests

## 15. Out of scope (explicito)

- ❌ Probe Chrome MCP de RPCs novos
- ❌ Featured/Explore (ub2Bae)
- ❌ Versionamento de outputs (historico de geracoes anteriores)
- ❌ Reimport de `more.design` (profile perdido — raw preservado fica
  como historico, nao sera atualizado)
- ❌ Cross-plataforma agora (depois das 7 verdes)
- ❌ Analise interpretativa (sentiment, clustering — outro projeto)

## 16. Riscos conhecidos

1. **Chat sempre None na sample** — schema do raw chat pode ser diferente
   do esperado. Mitigacao: empirical findings depois do full sync, antes do
   parser.
2. **`fetch_artifact` pode retornar payload posicional sem keys** (Google
   batchexecute pattern) — schema dos tipos 2/4/7/9 precisa ser descoberto
   empiricamente. Probes existentes (`notebooklm-probe-generators.py`)
   podem ter parte do mapeamento; revisar.
3. **`fetch_mind_map_tree` schema** — CYK0Xb retorno tambem precisa probe.
4. **Volume**: 95 notebooks na conta hello + N na marloon. Com binarios,
   dataset pode ser >5GB. Asset download eh skip-existing — primeira run
   demora, runs subsequentes sao incrementais.

## 17. Cronograma estimado

| Fase | Tarefa | Estimativa |
|---|---|---|
| 5 | Migrar orchestrator (multi-conta + pasta unica + bugs preventivos) | 0.5 dia |
| 5 | Adicionar `fetch_artifact` + `fetch_mind_map_tree` no fetcher | 0.5 dia |
| 6 | Migrar reconciler (multi-conta + FEATURES_VERSION=2) | 0.5 dia |
| 7 | Build `scripts/notebooklm-sync.py` | 0.25 dia |
| 8 | Run full sync (2 contas) — pode demorar com binarios | 0.5 dia |
| 9 | Empirical findings + server behavior docs | 0.5 dia |
| 10 | Parser v3 (8 parquets) + helpers + tests | 1.5 dias |
| 11 | Quarto descritivo (3 docs) | 0.5 dia |
| 12 | Bateria CRUD UI + ajustes | 0.25 dia |
| 13 | Review cruzado + CLAUDE.md update | 0.25 dia |
| **Total** | | **~5 dias** |

## 18. Anexos

- Brief: `~/.claude/projects/-Users-mosx-Desktop-multi-ai-session-data-extractor/memory/project_pickup_brief_notebooklm.md`
- Plan generico: `docs/platform-replication-plan.md` (8 fases por plataforma)
- Glossary: `docs/glossary.md`
- Estado das 6 plataformas shipped: `CLAUDE.md` §"Estado validado"
- Refs cross-plataforma: `notebooks/gemini.qmd` (modelo multi-conta)
