# Platform engineering records

`state.md` e o ponto de entrada tecnico de cada uma das 13 fontes. Leia-o
antes de alterar captura, reconciliacao ou parser. Os detalhes de endpoints,
probes e comportamento upstream ficam nos arquivos adicionais da fonte quando
existirem.

## Web

- [ChatGPT](web/chatgpt/state.md)
- [Claude.ai](web/claude-ai/state.md)
- [Gemini](web/gemini/state.md)
- [NotebookLM](web/notebooklm/state.md)
- [Qwen](web/qwen/state.md)
- [DeepSeek](web/deepseek/state.md)
- [Perplexity](web/perplexity/state.md)
- [Grok](web/grok/state.md)
- [Kimi](web/kimi/state.md)

Web sources may also contain `discovery.md`, `server-behavior.md` and dated
incident or parity reports.

## CLI

- [Claude Code](cli/claude-code/state.md)
- [Codex](cli/codex/state.md)
- [Gemini CLI](cli/gemini-cli/state.md)
- [Antigravity CLI](cli/antigravity-cli/state.md)

CLIs use the same `state.md` entry-point convention. They do not need a
`server-behavior.md` merely to mirror web sources: there is no upstream server
to document.
