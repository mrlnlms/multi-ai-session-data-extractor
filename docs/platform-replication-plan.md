# Replicação do padrão ChatGPT pras 6 plataformas restantes

Playbook pra trazer Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek e
Perplexity ao mesmo nível de cobertura que o ChatGPT já tem hoje
(2026-04-28). ChatGPT serve de **referência viva** — copiar estrutura,
adaptar gotchas.

---

## 1. Estado atual (atualizado 2026-05-01)

| Plataforma | Extractor | Reconciler | Sync orquestr. | Pasta única | Parser canônico | Script parse | QMD |
|---|---|---|---|---|---|---|---|
| **ChatGPT** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Perplexity** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Claude.ai** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Qwen** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **DeepSeek** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Gemini | ✅ | ✅ | ❌ | ❌ | ⚠️ legacy | ❌ | ❌ |
| NotebookLM | ✅ | ✅ | ❌ | ❌ | ⚠️ legacy | ❌ | ❌ |
| Qwen | ✅ | ✅ | ❌ | ❌ | ⚠️ legacy | ❌ | ❌ |
| DeepSeek | ✅ | ✅ | ❌ | ❌ | ⚠️ legacy | ❌ | ❌ |

**⚠️ legacy:** existe `src/parsers/<source>.py` mas é o MVP do projeto-mãe
(não no schema v3 — sem branches table, sem campos preservation, sem
ToolEvents estruturados). Precisa rewrite seguindo padrão do ChatGPT v3.

---

## 2. Princípio inegociável

**ChatGPT é referência viva. Replicar, não reinventar.** Cada artefato
abaixo tem espelho exato no ChatGPT — começar copiando, adaptar mínimo
necessário. Divergência semântica vs ChatGPT precisa de justificativa.

---

## 3. Sequência genérica (8 fases por plataforma)

### Fase A — Pasta única cumulativa (raw)

**Objetivo:** sair de "captura por timestamp" pra `data/raw/<Source>/`
mutável in-place.

- Adaptar `<source>-export.py` (ou orquestrador equivalente) pra usar
  `data/raw/<Source>/` fixo
- `LAST_CAPTURE.md` regenerado a cada run
- `capture_log.jsonl` append-only
- `_find_last_capture` no orchestrator do extractor

**Modelo:** `src/extractors/chatgpt/orchestrator.py` (`_resolve_output_dir`,
`_find_last_capture`, `_get_max_known_discovery`).

### Fase B — Sync orquestrador

**Objetivo:** `scripts/<source>-sync.py` que orquestra captura + assets +
reconcile em N etapas (varia por plataforma).

- Espelhar `scripts/chatgpt-sync.py` (4 etapas)
- Adaptar etapas conforme plataforma (algumas não têm "project sources"
  separado, outras têm tipos de assets diferentes)
- Flags consistentes: `--no-binaries`, `--no-reconcile`, `--full`, `--dry-run`

**Modelo:** `scripts/chatgpt-sync.py`.

### Fase C — Validação dos cenários CRUD

**Objetivo:** garantir o ciclo "capturar uma vez, nunca rebaixar"
end-to-end.

- Testar empiricamente os cenários aplicáveis à plataforma:
  - Conv deletada → preserved_missing
  - Conv atualizada → updated
  - Conv nova → added
  - Conv renomeada → updated (validar se servidor bumpa update_time)
  - Project criado/deletado (se aplicável)
- Documentar comportamento do servidor em
  `docs/<source>-server-behavior.md` (espelho de
  "Comportamento do servidor ChatGPT" no CLAUDE.md)

### Fase D — Empirical findings + fixtures

**Objetivo:** coletar features reais antes do parser canônico.

- Identificar features distintivas da plataforma (ex: Claude.ai tem
  thinking blocks, MCP integrations; Gemini tem Deep Research próprio;
  NotebookLM tem 9 tipos de outputs)
- Extrair fixtures sanitizadas em
  `tests/extractors/<source>/fixtures/raw_with_*.json`
- Meta-tests em `test_fixtures_integrity.py` por plataforma
- Doc empírico: `docs/<source>-parser-empirical-findings.md`

**Modelo:** `docs/parser-v3-empirical-findings.md` + 9 fixtures do ChatGPT.

### Fase E — Parser canônico (rewrite)

**Objetivo:** parser que entrega 4 parquets no schema v3.

- Reescrever `src/parsers/<source>.py` (não branchear o arquivo legacy —
  reescrever in-place; manter backup em
  `_backup-temp/parser-<source>-promocao-<date>/` durante validação)
- Schema canônico: Conversation, Message, ToolEvent, Branch
- `branch_id` não-opcional (default `<conv>_main` se sem fork)
- `is_preserved_missing` + `last_seen_in_server` em Conversation
- ToolEvents pra agentes/tools internos (se a plataforma tiver)
- Asset paths como `Optional[list[str]]` (nativo)
- Adaptações por plataforma (ver §5)

**Modelo:** `src/parsers/chatgpt.py` + helpers em `_chatgpt_helpers.py`.

### Fase F — Script CLI parse

**Objetivo:** `scripts/<source>-parse.py` consumindo merged → parquets.

- Lê `data/merged/<Source>/<source_lower>_merged.json`
- Escreve `data/processed/<Source>/{conversations, messages, tool_events, branches}.parquet`
- Idempotente (rodar 2x = mesmos bytes)

**Modelo:** `scripts/chatgpt-parse.py`.

### Fase G — Validação cruzada vs legacy

**Objetivo:** documentar paridade do parser novo vs antigo.

- Rodar parser legacy (em backup) e novo no mesmo merged
- Comparar contagens (convs, msgs, tool_events)
- Documentar diferenças em `docs/<source>-parser-validation.md`
- Critério: parser novo ⊇ parser antigo (pode ter mais — não pode ter menos)

**Modelo:** `docs/parser-v3-validation.md`.

### Fase H — Notebook Quarto descritivo

**Objetivo:** `notebooks/<source>.qmd` rendirizando HTML estático no
padrão "zero trato".

- Espelhar estrutura do `notebooks/chatgpt.qmd` (4 seções: Dados disponíveis,
  Cobertura, Volumes, Preservation)
- Adaptar gráficos/tabelas conforme features da plataforma
- Cor primária dedicada (define nova cor em `_style.css` ou inline)
- Render via `quarto render notebooks/<source>.qmd` em < 30s
- HTML self-contained < 100 MB

**Modelo:** `notebooks/chatgpt.qmd` (916 linhas, 4 seções, 5 figuras
plotly, 29 blocos Python).

---

## 4. Wire automático no dashboard

**Não precisa fazer nada explícito.** O dashboard Streamlit já:
- Descobre plataforma via `KNOWN_PLATFORMS` em `dashboard/data.py`
- Lê `LAST_CAPTURE.md` + `LAST_RECONCILE.md` + jsonls automaticamente
- Detecta `notebooks/<source>.qmd` e mostra botão "Ver dados detalhados"
  via `dashboard/quarto.py`
- Status badge cross-plataforma na tabela do overview

Quando os arquivos da Fase A-H existirem nos paths convencionais, dashboard
reflete automaticamente.

---

## 5. Particularidades conhecidas por plataforma

Cada plataforma tem features distintivas que o parser v3 precisa cobrir.
Lista informada pelo backlog do projeto-mãe e empírica observada.

### Claude.ai

**Complexidade alta.** Item #41 do backlog do projeto-mãe.

- **Thinking blocks** (extended thinking): 7k+ blocks no projeto-mãe.
  Campo `Message.thinking` já existe no schema; parser legacy pode estar
  ignorando.
- **Tool use/result blocks** (16k+): incluindo MCPs (`integration_name`,
  `mcp_server_url`, `is_mcp_app`). Vira ToolEvent.
- **Attachments com extracted_content** (1.8k+).
- **Project docs com content** (23M chars em 546 docs no projeto-mãe).
  Pode justificar tabela `project_docs` separada.
- **Branches via** `parent_message_uuid` + `current_leaf_message_uuid`
  (UUID-based, não tree-walk como ChatGPT).
- **Citations** em text blocks.
- **Summary** auto-gerado por conv.
- **Settings** por conv (feature flags).

**Captura:** headless ✅. Sync: 6 módulos em
`src/extractors/claude_ai/`.

### Gemini

**Complexidade média.**

- **API batchexecute** (rpcids `MaZiqc` list + `hNvQHb` fetch).
- **Multi-conta** via profiles `.storage/gemini-profile-{N}/`.
- **Deep Research próprio** (PDFs gerados — espelho do DR do ChatGPT).
- **Imagens** via `lh3.googleusercontent.com/gg/...` presigned URLs.
- 80 convs / 226 imagens no merged do projeto-mãe.

**Captura:** headless ✅.

### NotebookLM

**Complexidade alta — 9 tipos de outputs gerativos.**

- **Outputs:** Audio (1), Blog/Report (2), Video (3), Flashcards/Quiz (4),
  Data Table (7), Slide Deck (8 — PDF+PPTX), Infographic (9), Mind Map.
- Cada tipo precisa de tratamento específico no parser (asset_paths
  por tipo, content_type específico).
- **9 categorias de ToolEvent** específicas do NotebookLM.
- 1.874 arquivos / 2 contas no projeto-mãe.

**Captura:** headless ✅. Reconciler v2 com FEATURES_VERSION + build_plan.

### Perplexity ✅ shipped (2026-05-01)

Equiparado ao ChatGPT. Detalhes em `perplexity-audit-findings.md` e
`perplexity-journey-2026-05-01.md`. Sync + parser + Quarto entregues.
Gaps fechados via probes Chrome MCP: pin (bug em `list_all_threads`
corrigido), skills em spaces (`/rest/skills?scope=collection&scope_id=<UUID>`),
archive (Enterprise-only — backend aceita mas no-op pra Pro).

### Qwen / DeepSeek

**Complexidade baixa-média.**

- Padrão simples (chat texto + algumas tools básicas).
- Qwen, DeepSeek: headless ✅.
- Reconcilers ainda estão **pendentes** (item #46 do projeto-mãe) —
  fazer junto com sync orquestrador.

---

## 6. Critérios de pronto (por plataforma)

Cada plataforma só está "shipped" quando:

- ✅ Sync orquestrador funcional, idempotente
- ✅ Pasta única `data/raw/<Source>/` cumulativa
- ✅ `LAST_CAPTURE.md` + `LAST_RECONCILE.md` + jsonls atualizados
- ✅ Cenários CRUD aplicáveis validados empiricamente
- ✅ Parser canônico gera 4 parquets no schema v3
- ✅ Fixtures + meta-tests cobrem features distintivas
- ✅ Notebook Quarto rendiriza < 30s, HTML < 100MB
- ✅ Dashboard reflete a plataforma automaticamente
- ✅ Documentação atualizada (CLAUDE.md, plan empírico, validation)

---

## 7. Ordem sugerida (atualizada 2026-05-01)

**Por que importa:** cada plataforma é um pacote ~3-5 dias de trabalho.
Ordem certa minimiza retrabalho e gera momentum.

```
✅ Perplexity   ← shipped 2026-05-01 (sync + parser + Quarto + gaps fechados)

A fazer:

1. Claude.ai     ← maior complexidade, maior valor (thinking + MCPs)
                   destrava 80% do conteúdo hoje descartado

2. NotebookLM    ← 9 tipos de output, padrão complexo
                   serve de stress test pra schema v3

3. Gemini        ← multi-conta, Deep Research
                   exercita asset paths cross-account

4. Qwen          ← simples, exercita o caminho "happy path"
                   reconciler precisa primeiro (item #46)

5. DeepSeek      ← simples, similar ao Qwen
                   reconciler precisa primeiro
```

**Justificativa da ordem:** Perplexity foi feita primeiro (fora da ordem
original) porque é a de menor complexidade entre as headed e serviu de
"warm-up" pra confirmar a transferibilidade do padrão ChatGPT. Claude.ai
vem next porque (a) é a plataforma mais complexa — se o schema v3 não
comportar, descobrimos cedo; (b) é a de maior volume de conteúdo descartado
pelo parser legacy (thinking, MCP). NotebookLM em sequência porque os 9
tipos de output testam a robustez do schema.

---

## 8. Estimativa de esforço

| Plataforma | Sync + parser | Quarto | Total | Status |
|---|---|---|---|---|
| Perplexity | 1 dia | 0.5 dia | 1.5 dias | ✅ shipped 2026-05-01 |
| Claude.ai | 3-5 dias | 0.5 dia | 3.5-5.5 dias | pendente |
| NotebookLM | 3-4 dias | 0.5 dia | 3.5-4.5 dias | pendente |
| Gemini | 1-2 dias | 0.5 dia | 1.5-2.5 dias | pendente |
| Qwen | 1 dia | 0.5 dia | 1.5 dias | pendente |
| DeepSeek | 1 dia | 0.5 dia | 1.5 dias | pendente |
| **Pendente** | | | **~11-15 dias** |

Estimativas otimistas se padrão fluir. Add 30% de buffer pra surpresas
(API mudou, feature nova que não estava no findings, etc).

---

## 9. O que NÃO é objetivo deste plan

- ❌ Refazer o ChatGPT (já está pronto, é referência)
- ❌ Mudar schema canônico (definido no parser v3)
- ❌ Cross-plataforma agora (faz sentido depois de 2+ plataformas
  no padrão — espelhar `notebooks/00-overview.qmd` do projeto-mãe)
- ❌ DVC ainda (foi acordado: depois das 7 plataformas)
- ❌ Análise interpretativa (sentiment, clustering — fora do escopo)
- ❌ Migrar configs do projeto-mãe automaticamente (cada plataforma
  recebe config explícita, não via lookup)

---

## 10. Notas pra implementador

### 10.1. Não escrever plan formal por plataforma sem dados

Ler `docs/parser-v3-empirical-findings.md` — pattern foi: explorar dados
reais antes de plan. Plan especulativo vira refator. Pra cada plataforma:

1. Roda sync (Fase A+B) → tem merged em mãos
2. Explora interativamente em Positron/Jupyter (60-90 min)
3. Identifica features
4. Coleta fixtures (Fase D) **com base em dados reais**
5. Aí sim parser (Fase E)

### 10.2. Não branchear arquivos

Padrão estabelecido: rewrite in-place. Backup em
`_backup-temp/parser-<source>-promocao-<date>/` durante Fase G
(validação cruzada). Quando paridade confirmada, deleta backup.

`source_name` muda durante validação (`<source>_v3` → `<source>` quando
estável). Convenção: parser legacy fica deprecated, não removido até
nova base estabilizada.

### 10.3. Commits granulares

Seguir padrão estabelecido pelo ChatGPT — 1 commit por entrega lógica
(fixture, plan, parser, validation, etc). Use `~/.claude/scripts/commit.sh`.

### 10.4. Testes nunca regridem

Critério forte: cada plataforma adicionada deve **aumentar** o número de
testes da suite, não diminuir. Hoje (após ChatGPT): 253 passing.

### 10.5. CLAUDE.md atualizado a cada plataforma shipping

Padrão: ao terminar uma plataforma, atualizar:
- Tabela §1 (Status) — `❌ → ✅`
- Seção "Estado validado" — adicionar bloco com counts e features
- Seção "Comportamento do servidor" — se houver achado empírico

---

## 11. Quando parar

Quando todas as 7 plataformas tiverem todas as colunas verdes da §1 e o
dashboard mostrar 7 plataformas todas verdes na tabela cross-plataforma.

Aí o projeto está em estado **shipped** e abre espaço pra:
- Cross-plataforma (`notebooks/00-overview.qmd`)
- DVC pra dados grandes
- Publicação opensource (já deserva README adicional, exemplos)
- Captura por outros usuários (cada um com suas contas)
