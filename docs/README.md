# docs — índice

Documentação do projeto, organizada por tema.

## Universal — leitura recomendada antes de tocar o código

- **[SETUP.md](SETUP.md)** — guia detalhado do zero (instalação, login
  por plataforma, primeira captura, troubleshooting).
- **[LIMITATIONS.md](LIMITATIONS.md)** — gaps e limitações conhecidas
  (upstream, cobertura adicional pendente, testes).
- **[SECURITY.md](SECURITY.md)** — política de credenciais, ToS
  disclaimer, boas práticas antes de subir o repositório.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — como reportar issues, fazer
  PR, adicionar plataforma nova (8 fases), lições transferíveis.
- **[glossary.md](glossary.md)** — termos do projeto (discovery, merged,
  preserved_missing, fail-fast, parser canônico, branches, ToolEvent,
  data profile template, etc).
- **[operations.md](operations.md)** — comandos comuns no terminal (sync
  por plataforma, render Quarto, smoke tests, sintomas → causa).
- **[serve-qmds.md](serve-qmds.md)** — cheatsheet do `scripts/serve-qmds.sh`
  (sobe/derruba servidor local pros data profiles).
- **[cross-platform-features.md](cross-platform-features.md)** — pin,
  archive, voice, share por plataforma (cumulative cross-feature checks).

## Overview cross-platform

`data/unified/` materializa 11 parquets consolidados das 10 sources via
`scripts/unify-parquets.py`. 4 qmds em `notebooks/00-overview*.qmd`
(geral, web, cli, rag) consomem o unified com filtros diferentes.
Verbete completo em [glossary.md](glossary.md) seção "data/unified/".

## Por plataforma

Cada plataforma web tem `state.md` (cobertura técnica) +
`server-behavior.md` (comportamento upstream observado). Plataformas CLI
têm apenas `README.md` (são derivadas de arquivos locais, sem servidor).

| Plataforma | Tipo | Docs locais |
|---|---|---|
| **ChatGPT** | web | [README](platforms/chatgpt/README.md) · [state](platforms/chatgpt/state.md) · [server-behavior](platforms/chatgpt/server-behavior.md) |
| **Claude.ai** | web | [state](platforms/claude-ai/state.md) |
| **DeepSeek** | web | [state](platforms/deepseek/state.md) · [server-behavior](platforms/deepseek/server-behavior.md) |
| **Gemini** | web (multi-conta) | [state](platforms/gemini/state.md) · [server-behavior](platforms/gemini/server-behavior.md) |
| **NotebookLM** | web (multi-conta) | [state](platforms/notebooklm/state.md) · [server-behavior](platforms/notebooklm/server-behavior.md) |
| **Perplexity** | web | [state](platforms/perplexity/state.md) |
| **Qwen** | web | [state](platforms/qwen/state.md) · [server-behavior](platforms/qwen/server-behavior.md) |
| **Claude Code** | CLI | [README](platforms/claude-code/README.md) |
| **Codex** | CLI | [README](platforms/codex/README.md) |
| **Gemini CLI** | CLI | [README](platforms/gemini-cli/README.md) |

## Dashboard

- [dashboard/manual.md](dashboard/manual.md) — manual de funcionalidades
  + operação (Streamlit local, single-user, read-only).
