# multi-ai-session-data-extractor

Captura, reconcilia e parseia sessoes de AI multi-plataforma em schema canonico.

## Por que existe

Plataformas AI (ChatGPT, Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity) tem export oficial limitado, frequentemente quebrado, e nenhuma garantia de retencao. Este projeto captura via API interna (ou filesystem, no caso de manual saves) tudo que existe, reconcilia incrementalmente preservando historico de chats deletados no servidor, e parseia pra um schema canonico em parquet.

Output desenhado pra ser **fonte autoritativa**: depois de capturado, voce pode deletar do servidor e continuar usando as plataformas sem perder nada.

## Cobertura

### Extractors via API (web)

| Plataforma | Captura | Conteudo extraido |
|---|---|---|
| ChatGPT | API interna `/backend-api/` | conversations, projects, files, Canvas, Deep Research, DALL-E, voice transcripts |
| Claude.ai | API interna `/api/organizations/` | conversations, projects, docs, artifacts (1117+), thinking, MCP tool calls |
| Gemini | batchexecute API | conversations (multi-conta), Deep Research, imagens user + model-generated |
| NotebookLM | batchexecute API | notebooks, audio overview, video, slide deck (PDF+PPTX), blog, flashcards, quiz, data table, infographic, mind map, source content |
| Qwen | API interna | conversations, attachments |
| DeepSeek | API interna | conversations |
| Perplexity | API interna | conversations, attachments |

### Extractors via filesystem (CLI)

| Fonte | Localizacao |
|---|---|
| Claude Code | `~/.claude/` (live, copia incremental) |
| Codex | `~/.codex/` |
| Gemini CLI | `~/.gemini/` |

### Importers (manual saves)

Conversas salvas manualmente no filesystem (clippings Obsidian, copy-paste de browser, transcripts de terminal pre-pipeline). Mesmo schema canonico.

## Arquitetura

```
data/raw/<source> Data <date>/      # output dos extractors
                                    # output dos importers (manual saves)
        ↓
data/merged/<source>/<date>/        # output dos reconcilers (preserved_missing)
        ↓
data/processed/<source>.parquet     # output dos parsers (schema canonico)
```

Schema canonico: `Conversation`, `Message`, `ToolEvent`, `ConversationProject` (em `src/schema/models.py`).

## Status

Em scaffold inicial. Migracao do projeto `ai-interaction-analysis` em curso.
