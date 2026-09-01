# docs — index

Project documentation, organized by topic.

## Product direction

- **[PERSONAL_AI_ARCHIVE.md](PERSONAL_AI_ARCHIVE.md)** — validated product
  vision for operation, archive/reader and assisted curation; not an
  implementation spec.
- **[ROADMAP.md](ROADMAP.md)** — current priorities, operational work and the
  recommended reading map for humans and agents.
- **[data-identity-and-reader-fidelity.md](data-identity-and-reader-fidelity.md)**
  — audit and future contract for stable references, CLI events and faithful
  conversation rendering.
- **[account-instances-and-application-architecture.md](account-instances-and-application-architecture.md)**
  — paused architectural exploration of multi-account instances, application
  packaging/security and the consumer snapshot boundary; decisions remain open.

## Universal — recommended reading before touching the code

- **[SETUP.md](SETUP.md)** — detailed guide from zero (installation, login
  per platform, first capture, troubleshooting).
- **[LIMITATIONS.md](LIMITATIONS.md)** — known gaps and limitations
  (upstream, additional pending coverage, tests).
- **[SECURITY.md](SECURITY.md)** — credentials policy, ToS
  disclaimer, best practices before pushing the repository.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to report issues, open
  PRs, add a new platform (8 phases), transferable lessons.
- **[glossary.md](glossary.md)** — project terms (discovery, merged,
  preserved_missing, fail-fast, canonical parser, branches, ToolEvent,
  data profile template, etc.).
- **[operations.md](operations.md)** — common terminal commands (sync
  per platform, Quarto render, smoke tests, symptoms → cause).
- **[WEB_COLLECTION_HANDOFF.md](WEB_COLLECTION_HANDOFF.md)** — operational
  runbook and handoff contract for refreshing web sources safely.
- **[data-storage-inventory.md](data-storage-inventory.md)** — storage
  baseline after recovery: DVC logical/cache sizes, largest consumers and
  Drive versus R2 considerations.
- **[serve-qmds.md](serve-qmds.md)** — `scripts/serve-qmds.sh` cheatsheet
  (start/stop local server for the data profiles).
- **[cross-platform-features.md](cross-platform-features.md)** — pin,
  archive, voice, share per platform (cumulative cross-feature checks).

## Cross-platform overview

`data/unified/` materializes 13 consolidated parquets from the 13 sources via
`scripts/unify-parquets.py`. 4 qmds in `notebooks/00-overview*.qmd`
(general, web, cli, rag) consume the unified set with different filters.
Full entry in [glossary.md](glossary.md) section "data/unified/".

## Per platform

Each web platform has `state.md` (technical coverage) +
`server-behavior.md` (observed upstream behavior). CLI platforms
have only `README.md` (they're derived from local files, no server).

| Platform | Type | Local docs |
|---|---|---|
| **ChatGPT** | web | [README](platforms/chatgpt/README.md) · [state](platforms/chatgpt/state.md) · [server-behavior](platforms/chatgpt/server-behavior.md) |
| **Claude.ai** | web | [state](platforms/claude-ai/state.md) |
| **DeepSeek** | web | [state](platforms/deepseek/state.md) · [server-behavior](platforms/deepseek/server-behavior.md) |
| **Gemini** | web (multi-account) | [state](platforms/gemini/state.md) · [server-behavior](platforms/gemini/server-behavior.md) |
| **NotebookLM** | web (multi-account) | [state](platforms/notebooklm/state.md) · [server-behavior](platforms/notebooklm/server-behavior.md) |
| **Perplexity** | web | [state](platforms/perplexity/state.md) |
| **Qwen** | web | [state](platforms/qwen/state.md) · [server-behavior](platforms/qwen/server-behavior.md) |
| **Grok** | web | [state](platforms/grok/state.md) · [recon](platforms/grok/recon.md) · [export analysis](platforms/grok/export-analysis.md) |
| **Kimi** | web | [state](platforms/kimi/state.md) · [server-behavior](platforms/kimi/server-behavior.md) |
| **Claude Code** | CLI | [README](platforms/claude-code/README.md) |
| **Codex** | CLI | [README](platforms/codex/README.md) |
| **Gemini CLI** | CLI | [README](platforms/gemini-cli/README.md) |
| **Antigravity CLI** | CLI | [README](platforms/antigravity-cli/README.md) |

## Dashboard

- [dashboard.md](dashboard.md) — features manual
  + operation (local Streamlit, single-user, read-only).

## Registro historico

- [RECOVERY.md](RECOVERY.md) — reconciliation completed in August 2026;
  historical audit record, not a current operational procedure.
