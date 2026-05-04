# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.

Formato baseado em [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versionamento [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-04

Primeira release pública. Estado de cobertura ao publicar:

### Plataformas web (7) — sync + reconcile + parser canônico v3 + Quarto descritivo

- **ChatGPT** — referência viva. Pasta única cumulativa, sync 4 etapas (capture
  + assets + project_sources + reconcile), captura headed (Cloudflare),
  fail-fast contra discovery flakey. Cobre branches off-path, voice
  (in/out), DALL-E, canvas, deep_research, custom_gpt vs project.
- **Claude.ai** — sync 3 etapas headless. Branches via DAG plano, thinking
  blocks, tool_use/result com MCP detection (3 sinais), attachments com
  extracted_content inline, project docs queryable.
- **Perplexity** — sync 2 etapas headed. Threads + spaces (collections) +
  pages (articles) + artifacts (assets). Pin via `list_pinned_ask_threads`
  POST `{}`, skills via scope-based endpoint, archive Enterprise-only
  (no-op em Pro/free).
- **Qwen** — sync 2 etapas headless. 8 chat_types (chat/search/research/
  dalle/etc), reasoning_content em thinking, t2i/t2v como ToolEvent.
- **DeepSeek** — sync 2 etapas headless. R1 reasoning em ~31% das msgs,
  branches DAG plano com muito regenerate (~2.4 branches/conv).
- **Gemini** — sync 3 etapas multi-conta headless. Schema posicional
  (batchexecute, sem keys nomeados) descoberto via probe. Pin via
  `c[2]` do listing MaZiqc, search/grounding citations.
- **NotebookLM** — sync 3 etapas multi-conta headless. 9 parquets (4
  canônicos + 5 auxiliares pra sources/notes/outputs/guide_questions/
  source_guides). 9 RPCs mapeados. `guide.summary` vira system message
  pra garantir `message_count >= 1`.

### CLIs (3) — copy + parser canônico v3

- **Claude Code** — copy de `~/.claude/projects/`, sub-agents como
  `interaction_type='ai_ai'`.
- **Codex** — copy de `~/.codex/sessions/`, function_call ↔
  exec_command_end correlacionados.
- **Gemini CLI** — copy de `~/.gemini/tmp/`, multi-snapshot consolidado
  via dedup por message_id.

### Manual saves (3 parsers)

- `clippings_obsidian` — clippings de extensão Obsidian.
- `copypaste_web` — colagens manuais de UI das plataformas.
- `terminal_claude_code` — outputs de terminal capturados manualmente.

`Conversation.capture_method` (schema v3.2) distingue `extractor` /
`manual_*` / `legacy_*`.

### Cross-platform overview

- `scripts/unify-parquets.py` materializa 11 parquets consolidados em
  `data/unified/` via concat + dedup com PK composta.
- 4 Quarto overviews (`00-overview*.qmd`): geral, web, cli, rag.

### Dashboard Streamlit

- Discovery automática de plataformas via `KNOWN_PLATFORMS`.
- Render Quarto via subprocess + symlink pra `static/quarto/` (sem
  duplicação de disco).
- Detecção de HTML stale (parquets > último render).

### Schema canônico v3.2

`src/schema/models.py`:

- `Conversation`, `Message`, `ToolEvent`, `Branch` — 4 tabelas canônicas.
- `ProjectMetadata`, `ProjectDoc` — auxiliares pra plataformas com projects.
- `NotebookLM*` — 5 auxiliares específicas (sources, notes, outputs,
  guide_questions, source_guides).
- `is_preserved_missing` + `last_seen_in_server` — preservation universal.
- `is_pinned`, `is_archived`, `is_temporary` — flags cross-platform.
- `capture_method` — distingue extractor / manual / legacy.

### Princípios

- Capturar uma vez, nunca rebaixar (pasta única cumulativa + skip_existing).
- Preservation acima de tudo (`_preserved_missing` em convs e sources).
- Fail-fast contra discovery flakey (threshold 20%).
- Schema canônico é fronteira (extractors/parsers convertem; análise lê
  parquet read-only).

### Testes

- 514 testes passando em Python 3.12 e 3.13.
- Cobre todos os 10 parsers, schema, helpers de notebook, unify, 7
  reconcilers (smoke + idempotência), funções puras dos 6 extractors web.

### Documentação

- `docs/SETUP.md`, `docs/CONTRIBUTING.md` (com playbook de 8 fases pra
  adicionar plataforma nova + 10 lições transferíveis), `docs/SECURITY.md`,
  `docs/LIMITATIONS.md`, `docs/glossary.md`, `docs/operations.md`.
- `docs/platforms/<plat>/{state,server-behavior}.md` por plataforma.
- `docs/cross-platform-features.md` — pin/archive/voice/share por
  plataforma.

### Infraestrutura

- GitHub Actions: pytest em Python 3.12 + 3.13 a cada push/PR.
- Issue + PR templates.
- pyproject.toml com metadata + dependências.

[Unreleased]: https://github.com/mrlnlms/multi-ai-session-data-extractor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mrlnlms/multi-ai-session-data-extractor/releases/tag/v0.1.0
