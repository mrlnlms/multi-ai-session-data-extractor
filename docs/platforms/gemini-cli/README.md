# Gemini CLI

Source: `gemini_cli`. Mode: `cli`. Dado local — copy incremental de
`~/.gemini/tmp/`.

## Especificidades do schema

- **Schema JSON** (não JSONL como Claude Code/Codex): `session-<timestamp>-<sid>.json`
- **Snapshots periódicos:** mesma sessão pode ter N arquivos com mesmo
  `sessionId` interno. Parser consolida em 1 Conversation com dedup por
  `message_id`. Ver `src/parsers/gemini_cli.py:_parse_session`.
- `thoughts` array → `thinking` formatado.
- `toolCalls` correlacionados via status (`success`/`error`).

## Por quê não tem `server-behavior.md`

CLI não tem servidor. Ver `docs/platforms/claude-code/README.md` pra
padrão "preservation a nível de raw via cli-copy".

## Onde a info real mora

- **Parser:** `src/parsers/gemini_cli.py`
- **Copy script:** `src/extractors/cli/copy.py`
- **Quarto data profile:** `notebooks/gemini-cli.qmd`
- **Sync orquestrador:** `scripts/gemini-cli-sync.py`
