# Contribuindo

Este projeto aceita contribuições — issues, PRs, novas plataformas,
melhorias de doc.

## Como reportar um problema

1. Verifique se o problema já está em [LIMITATIONS.md](LIMITATIONS.md).
   Algumas coisas são limitações conhecidas (não bugs).
2. Reproduza o problema com o último estado do código (`git pull`).
3. Abra uma issue com:
   - Plataforma afetada (ex: ChatGPT, Claude.ai)
   - Comando exato que rodou
   - Erro completo (stderr, traceback)
   - Versão Python (`python3 --version`)
   - macOS ou Linux

Para vulnerabilidades de segurança, ver [SECURITY.md](SECURITY.md).

## Como fazer um Pull Request

1. **Fork + branch.** Não trabalhe em `main`.
2. **Rode os testes** antes de submeter:
   ```bash
   PYTHONPATH=. .venv/bin/pytest
   ```
   Todos os 514+ testes precisam passar.
3. **Adicione testes** para mudanças de comportamento. Padrões em
   `tests/parsers/test_*.py`.
4. **Mantenha o estilo** do código existente. Não há linter automático;
   siga o que já está lá.
5. **Commit messages** em português ou inglês, no estilo conventional
   commits (`feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`,
   `test: ...`).
6. **Atualize a documentação** quando aplicável.

### Antes do PR

- [ ] Testes passam (`pytest`)
- [ ] Sem credenciais commitadas (`git diff` limpo)
- [ ] Mudança documentada onde apropriado
- [ ] Commits assinados com seu nome real

## Adicionando uma plataforma nova

ChatGPT é a **referência viva** — copie a estrutura, adapte o mínimo
necessário. Divergência semântica vs ChatGPT precisa de justificativa.
Cada plataforma é um pacote ~3-5 dias de trabalho.

### Princípio

**Replicar, não reinventar.** Cada artefato abaixo tem espelho exato no
ChatGPT — começar copiando, adaptar mínimo necessário.

### Sequência genérica (8 fases por plataforma)

#### Fase A — Pasta única cumulativa (raw)

**Objetivo:** captura mutável in-place em `data/raw/<Source>/` (sem
timestamp).

- Adaptar `<source>-export.py` (ou orquestrador equivalente) pra usar
  `data/raw/<Source>/` fixo.
- `LAST_CAPTURE.md` regenerado a cada run.
- `capture_log.jsonl` append-only.
- `_find_last_capture` no orchestrator do extractor.

**Modelo:** `src/extractors/chatgpt/orchestrator.py` (`_resolve_output_dir`,
`_find_last_capture`, `_get_max_known_discovery`).

#### Fase B — Sync orquestrador

**Objetivo:** `scripts/<source>-sync.py` que orquestra captura + assets +
reconcile em N etapas (varia por plataforma).

- Espelhar `scripts/chatgpt-sync.py` (4 etapas).
- Adaptar etapas conforme plataforma (algumas não têm "project sources"
  separado, outras têm tipos de assets diferentes).
- Flags consistentes: `--no-binaries`, `--no-reconcile`, `--full`,
  `--dry-run`.

**Modelo:** `scripts/chatgpt-sync.py`.

#### Fase C — Validação dos cenários CRUD

**Objetivo:** garantir o ciclo "capturar uma vez, nunca rebaixar"
end-to-end.

Testar empiricamente os cenários aplicáveis à plataforma:

- Conv deletada → `is_preserved_missing=True`.
- Conv atualizada (mensagem nova) → `updated`, timestamp bumpa.
- Conv nova → `added`.
- Conv renomeada → `updated` (validar se servidor bumpa update_time).
- Project criado/deletado (se aplicável) → preservation no `_files.json`.

Documentar comportamento do servidor em
`docs/platforms/<plat>/server-behavior.md`.

#### Fase D — Empirical findings + fixtures

**Objetivo:** coletar features reais antes do parser canônico.

- Identificar features distintivas (ex: Claude.ai tem thinking blocks +
  MCP integrations; Gemini tem Deep Research; NotebookLM tem 9 tipos de
  outputs).
- Extrair fixtures sanitizadas em
  `tests/extractors/<plat>/fixtures/raw_with_*.json`.
- Meta-tests em `test_fixtures_integrity.py` por plataforma.

**Modelo:** 9 fixtures do ChatGPT em
`tests/extractors/chatgpt/fixtures/`.

#### Fase E — Parser canônico

**Objetivo:** parser que entrega 4 parquets no schema v3.

- Reescrever `src/parsers/<source>.py` (não branchear o arquivo legacy —
  reescrever in-place; manter backup em
  `_backup-temp/parser-<source>-promocao-<date>/` durante validação).
- Schema canônico: `Conversation`, `Message`, `ToolEvent`, `Branch`.
- `branch_id` não-opcional (default `<conv>_main` se sem fork).
- `is_preserved_missing` + `last_seen_in_server` em Conversation.
- ToolEvents pra agentes/tools internos (se a plataforma tiver).
- Asset paths como `Optional[list[str]]` (nativo).

**Modelo:** `src/parsers/chatgpt.py` + helpers em `_chatgpt_helpers.py`.

#### Fase F — Script CLI parse

**Objetivo:** `scripts/<source>-parse.py` consumindo merged → parquets.

- Lê `data/merged/<Source>/<source_lower>_merged.json`.
- Escreve `data/processed/<Source>/{conversations, messages, tool_events,
  branches}.parquet`.
- Idempotente (rodar 2x = mesmos bytes).

**Modelo:** `scripts/chatgpt-parse.py`.

#### Fase G — Validação cruzada vs legacy (se houver legacy)

**Objetivo:** documentar paridade do parser novo vs antigo.

- Rodar parser legacy (em backup) e novo no mesmo merged.
- Comparar contagens (convs, msgs, tool_events).
- Documentar diferenças.
- Critério: parser novo ⊇ parser antigo (pode ter mais — não pode ter
  menos).

#### Fase H — Notebook Quarto descritivo

**Objetivo:** `notebooks/<source>.qmd` rendirizando HTML estático no
padrão "zero trato".

- Template canônico em `notebooks/_template.qmd` + helpers em
  `src/parsers/quarto_helpers.py`. Per-source qmd tem ~50 linhas — só
  config (`SOURCE_KEY`, `SOURCE_TITLE`, `SOURCE_COLOR`, `PROCESSED`,
  `TABLES`, `AUX_TABLES`, `ACCOUNT_FILTER`) + `setup_notebook(...)` +
  `{{< include _template.qmd >}}`.
- Cor primária da plataforma em `SOURCE_COLOR` (constante única).
- Tabelas auxiliares: adicionar nomes em `AUX_TABLES = [...]` + incluir
  `_template_aux.qmd`.
- Render via `quarto render notebooks/<source>.qmd` em ~20-60s.
- HTML self-contained ~40 MB (embed-resources).

**Modelo:** qualquer um dos 14 qmds — `notebooks/codex.qmd` é o menor
(~49 linhas).

### Critérios de pronto

Cada plataforma só está "shipped" quando:

- ✅ Sync orquestrador funcional, idempotente.
- ✅ Pasta única `data/raw/<Source>/` cumulativa.
- ✅ `LAST_CAPTURE.md` + `LAST_RECONCILE.md` + jsonls atualizados.
- ✅ Cenários CRUD aplicáveis validados empiricamente.
- ✅ Parser canônico gera 4 parquets no schema v3.
- ✅ Fixtures + meta-tests cobrem features distintivas.
- ✅ Notebook Quarto rendiriza < 30s, HTML < 100MB.
- ✅ Dashboard reflete a plataforma automaticamente.
- ✅ Documentação atualizada (`docs/platforms/<plat>/state.md` +
  `server-behavior.md`).

### Lições transferíveis

Padrões observados ao adicionar plataformas anteriores. Vale ler antes de
começar:

1. **Network tap > chute.** Não chutar URLs de endpoints. UI name e API
   name divergem (Perplexity: Spaces/collections, Pages/articles,
   Artifacts/assets). Use Playwright `page.on("response")` durante
   navegação manual real pra capturar XHRs verdadeiros.

2. **SSR pode esconder dados.** SPAs com router programático
   (`router.push` no onClick) não têm `<a href>` literais. Solução:
   DOM-click programático (`row.click()` + `expect_navigation()`).

3. **Conta free limita testes.** Features Pro/Enterprise podem aparecer
   no DOM mas retornar 404 ou modal "Upgrade". Documentar em
   `LIMITATIONS.md` em vez de assumir bug.

4. **Reconciler precisa cobrir cenários divergentes de delete.** "Delete"
   pode comportar diferente: thread some de tudo (`ENTRY_DELETED` em
   todos listings) vs sumiu de listing global mas continua referenciada
   em algum contêiner (orphan passivo). Marcar **ambos** como preserved.

5. **Discovery file naming.** Raw e merged podem ter nomes diferentes
   pro mesmo conceito. Reconciler precisa tentar ambos os nomes, não
   falhar silenciosamente.

6. **Server bumps update_time em rename.** Empiricamente em ChatGPT,
   Perplexity, Qwen, DeepSeek. Caminho incremental normal cobre — não
   precisa detecção especial. Guardrail extra (comparar title vs
   prev_raw) ajuda como defesa em profundidade.

7. **Manifest com status pra idempotência.** Uploads antigos podem ser
   irrecuperáveis (S3 cleanup, parents deletados). Marcar entries como
   `failed_upstream_deleted` evita re-tentar a cada run.

8. **Schema posicional vs nomeado.** Algumas APIs usam estruturas
   posicionais (Gemini batchexecute: `turn[3][0][0][1]`). Documentar
   exaustivamente os indexes em `<plat>-probe-findings.md`.

9. **Plan especulativo vira refator.** Explorar dados reais antes de
   plan formal economiza trabalho. Sequência: sync básico → exploração
   interativa (60-90 min) → identificar features → fixtures → parser.

10. **Não branchear arquivos.** Padrão estabelecido: rewrite in-place.
    Backup em `_backup-temp/` durante validação cruzada. Quando paridade
    confirmada, deleta backup.

### Particularidades já mapeadas

Ao começar uma plataforma já existente (ex: estender Claude.ai), conferir
primeiro:

- `docs/platforms/<plat>/state.md` — cobertura atual.
- `docs/platforms/<plat>/server-behavior.md` — comportamento upstream
  observado.
- `docs/cross-platform-features.md` — checks cross (pin, archive, voice,
  share).

## Padrões do projeto

### Idioma

- **Código:** inglês (nomes de funções, variáveis, classes).
- **Comentários e docs:** português ou inglês — seja consistente dentro
  do arquivo.
- **Commit messages:** português ou inglês.

### Estilo de código

- Tipo hints onde ajudam (não obrigatório em tudo).
- Docstrings em funções públicas e em casos com lógica não-óbvia.
- `from __future__ import annotations` no topo de novos módulos.
- Sem linter configurado — siga o estilo dos arquivos existentes.

### Testes

- `tests/` mirrors `src/` (`tests/parsers/test_<X>.py` pra
  `src/parsers/<X>.py`).
- Use fixtures sanitizadas em `tests/extractors/<plat>/fixtures/` para
  testar parsing — **não commite dados pessoais reais**.
- Testes devem rodar em <5s no total. Se um teste é lento, ou ele
  precisa ser quebrado, ou justifique no docstring.
- **Testes nunca regridem.** Cada plataforma adicionada deve **aumentar**
  o número de testes da suite, não diminuir.

### Schema canônico

`src/schema/models.py` define a estrutura — `Conversation`, `Message`,
`ToolEvent`, `Branch`. Mudanças no schema são **breaking changes** —
discuta numa issue antes de propor PR.

Schema atual: v3.2 (introduziu `capture_method` em Conversation).

### Princípios inegociáveis

1. **Capturar uma vez, nunca rebaixar.** Pasta única cumulativa +
   `skip_existing` nos downloaders.
2. **Preservation acima de tudo.** Conversas/arquivos deletados no
   servidor permanecem locais com `is_preserved_missing=True`.
3. **Schema canônico é a fronteira.** Particularidades de plataforma
   não vazam para a etapa de análise.
4. **Fail-fast contra discovery flakey** — discovery <80% do histórico
   aborta antes do save.

## Onde achar contexto

- [README.md](../README.md) — visão geral.
- [docs/README.md](README.md) — índice da documentação.
- [docs/glossary.md](glossary.md) — termos do projeto.
- [docs/platforms/](platforms/) — `state.md` + `server-behavior.md` por
  plataforma.
- [docs/cross-platform-features.md](cross-platform-features.md) — pin,
  archive, voice, share por plataforma.

## Comportamento esperado

Issues e PRs serão revisados quando o mantenedor tiver tempo. Não há
SLA. Para mudanças grandes, abra uma issue de discussão antes de
investir tempo em código.

Se a contribuição não se encaixar no escopo do projeto (ex: features de
análise interpretativa — sentiment, clustering, topic detection — que
explicitamente não pertencem aqui), ela pode ser fechada sem merge.
Discutir cedo evita retrabalho.
