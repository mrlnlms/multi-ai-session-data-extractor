# docs — índice

Documentação do projeto, organizada por tema. Padrão: docs vivos no root,
docs por plataforma em `platforms/<plat>/`, planos/findings transversais
em pastas dedicadas, stubs e superados em `archive/`.

## Universal — leitura recomendada antes de tocar o código

- **[SETUP.md](SETUP.md)** — guia detalhado do zero (instalação, login
  por plataforma, primeira captura, troubleshooting).
- **[LIMITATIONS.md](LIMITATIONS.md)** — gaps e limitações conhecidas
  (upstream, cobertura adicional pendente, testes).
- **[SECURITY.md](SECURITY.md)** — política de credenciais, ToS
  disclaimer, boas práticas antes de subir o repositório.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — como reportar issues, fazer
  PR, adicionar plataforma nova, padrões do projeto.
- **[glossary.md](glossary.md)** — termos do projeto (discovery, merged,
  preserved_missing, fail-fast, parser canônico, branches, ToolEvent, data
  profile template, etc).
- **[operations.md](operations.md)** — comandos comuns no terminal (sync por
  plataforma, render Quarto, smoke tests, sintomas → causa).
- **[serve-qmds.md](serve-qmds.md)** — cheatsheet do `scripts/serve-qmds.sh`
  (sobe/derruba servidor local pros data profiles).

## Overview cross-platform

`data/unified/` materializa 11 parquets consolidados das 10 sources via
`scripts/unify-parquets.py`. 4 qmds em `notebooks/00-overview*.qmd`
(geral, web, cli, rag) consomem o unified com filtros diferentes.
Verbete completo em [glossary.md](glossary.md) seção "data/unified/".
Arquitetura no CLAUDE.md seção "Overview cross-platform".

## Parser canônico v3

- [parser-v3/plan.md](parser-v3/plan.md) — plan formal do rewrite (status
  IMPLEMENTADO desde 2026-04-28 — referência histórica).
- [parser-v3/empirical-findings.md](parser-v3/empirical-findings.md) —
  achados empíricos do raw ChatGPT (1171 convs).
- [parser-v3/validation.md](parser-v3/validation.md) — validação cruzada v2
  vs v3 (cobertura, idempotência, regressões).
- [parser-v3/platform-replication-plan.md](parser-v3/platform-replication-plan.md)
  — playbook 8 fases pra trazer outras plataformas ao mesmo padrão (todas as
  7 web shipped + 3 CLIs em 2026-05-03).

## Dashboard

- [dashboard/manual.md](dashboard/manual.md) — manual de funcionalidades
  + operação (Streamlit local, single-user, read-only).
- [dashboard/plan.md](dashboard/plan.md) — plan formal das 4 fases (todas
  shipped — referência histórica de decisões).

## Por plataforma — empirical findings + server behavior

Empirical findings = o que o servidor expõe (probe sobre o raw). Server
behavior = o que o servidor faz quando o usuário renomeia/pina/deleta
(bateria CRUD UI).

| Plataforma | Findings | Server behavior |
|---|---|---|
| **Claude.ai** | [empirical](platforms/claude-ai/parser-empirical-findings.md) + [validation](platforms/claude-ai/parser-validation.md) | (consolidado em CLAUDE.md) |
| **DeepSeek** | [probe-findings](platforms/deepseek/probe-findings-2026-05-01.md) | [server-behavior](platforms/deepseek/server-behavior.md) |
| **Gemini** | (consolidado em CLAUDE.md) | [server-behavior](platforms/gemini/server-behavior.md) |
| **NotebookLM** | [probe-findings](platforms/notebooklm/probe-findings-2026-05-02.md) | [server-behavior](platforms/notebooklm/server-behavior.md) |
| **Perplexity** | [audit-findings](platforms/perplexity/audit-findings.md) + [journey](platforms/perplexity/journey-2026-05-01.md) + [pending-validations](platforms/perplexity/pending-validations.md) | (no audit-findings) |
| **Qwen** | [probe-findings](platforms/qwen/probe-findings-2026-05-01.md) | [server-behavior](platforms/qwen/server-behavior.md) |
| **ChatGPT** | [README](platforms/chatgpt/README.md) (pointer pra CLAUDE.md) | (no CLAUDE.md) |
| **Claude Code (CLI)** | [README](platforms/claude-code/README.md) | (CLI sem server) |
| **Codex (CLI)** | [README](platforms/codex/README.md) | (CLI sem server) |
| **Gemini CLI** | [README](platforms/gemini-cli/README.md) | (CLI sem server) |

## Archive — superados/stubs

Mantidos pra rastreabilidade histórica, mas conteúdo está em outro lugar:

- [archive/dashboard-operations.md](archive/dashboard-operations.md) —
  consolidado em `dashboard/manual.md` §10.
- [archive/perplexity-manual-test-checklist.md](archive/perplexity-manual-test-checklist.md)
  — superado pela bateria CRUD UI executada em 2026-05-01 (ver
  `platforms/perplexity/audit-findings.md`).

## Superpowers (workflow)

[superpowers/](superpowers/) — specs e plans que guiaram migrações grandes
(NotebookLM schema design, etc). Não é doc do projeto — é trace do trabalho.
