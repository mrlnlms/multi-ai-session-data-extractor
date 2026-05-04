# Limitações conhecidas

Lista honesta do que **não funciona** ou **não foi validado**. Atualizada
em 2026-05-04.

Limitações se dividem em 3 categorias:

- **Upstream** — a plataforma não expõe a feature; sem o que fazer no
  nosso lado.
- **Cobertura adicional pendente** — a feature existe, mas precisa de
  trabalho de mapeamento (probe ao vivo na plataforma).
- **Cobertura de testes** — o código funciona empiricamente mas há gaps
  de teste automatizado.

## Por plataforma

### ChatGPT

- **Voice — 97% das transcrições já capturadas via Pass 1.** 127 de 131
  voice messages têm texto da transcrição populado (via raw heuristic
  detectando `audio_transcription` em parts). 4 messages voice ficam
  com texto vazio (edge cases — transcrição falhou upstream). O Pass 2
  via DOM scraping (`src/extractors/chatgpt/dom_voice.py`) existe mas
  não é necessário pra essa cobertura — over-engineering pros 4 casos
  remanescentes.
- **8 assets irrecuperáveis:** alguns assets antigos não estão mais
  disponíveis no servidor (parents foram apagados). Documentado como
  "failed=8" no download — não é bug.

### Claude.ai

- **`is_archived` — sempre None:** Claude.ai não expõe esse campo em
  nenhum endpoint visível. Pra distinguir "não está arquivado" de
  "informação não disponível", o parser usa `None` em vez de `False`.

### Perplexity

- **Archive — Enterprise-only:** o backend aceita os requests
  `archive_thread`/`unarchive_thread` em contas Pro (200 success), mas
  o estado archived **não é exposto** em nenhum listing visível em
  Pro/free. Listar threads arquivadas só funciona em conta Enterprise
  (gated por Cloudflare Access). Pra contas Pro, archive é no-op
  observável — não é gap do extractor.
- **Voice em Perplexity** — o servidor transcreve e descarta o áudio,
  sem `is_voice` no schema. Não há como saber retroativamente se uma
  mensagem foi originalmente de voz.
- **1 thread orphan em GAS:** a thread `d344c501` é referenciada num
  space mas foi deletada do servidor. Preservada localmente como
  `is_preserved_missing=True`.

### Qwen

- **Archive — no-op upstream:** o servidor aceita o request mas a flag
  `archived` nunca persiste; `archived=True` nunca aparece em listings.
  Mesmo padrão do Perplexity — não é gap do extractor.
- **Temporary chats:** Qwen não tem essa feature. Campo `is_temporary`
  fica `None`.
- **`/v2/chats/archived` retorna sempre vazio** mesmo após archive
  request. Documentado.

### DeepSeek

- **`is_archived` e `is_temporary` — sempre None:** DeepSeek não expõe
  essas features. Padrão None (não False) pra deixar claro.
- **`message_id` é INT local-por-conv (1-98):** não é UUID global. Pra
  consolidação cross-platform, o `unify-parquets.py` usa PK composta
  `[source, conversation_id, message_id]`.

### Gemini

- **Drafts/regenerate alternativos:** quando você regera uma resposta,
  o estado anterior fica em `turn[1]` mas o parser v3 não captura — só
  o estado ativo. (Backlog: implementar quando aparecer caso real
  representativo.)
- ~~**Search/grounding citations**~~ **FECHADO 2026-05-04**: tool events
  tipo `search_result` são criados (1 por citation com URL, título,
  snippet, favicon, deduplicados por URL). Também populam
  `Message.citations_json` no parquet de mensagens. Base atual: 416
  search results em 9 messages que usaram Deep Research.
- **Share URL:** Gemini permite compartilhar uma conversa por URL
  pública. Esse estado não é gravado no body da conv (o servidor gera a
  URL e mantém isolada). Não é gap do extractor — não é capturável.
- **Multi-conta:** suporte para 2 contas Google é hardcoded (acc-1, acc-2).
  Para mais contas, seria necessário ajustar `gemini-sync.py` e o
  template Quarto.

### NotebookLM

- **Não tem feature de pin** upstream — campo `is_pinned` fica `None`.
- **`update_time` no listing é volátil** — o servidor reindexa
  periodicamente e bumpa o timestamp sem mudança real de conteúdo. O
  reconciler usa hash semântico (não timestamp) pra decidir refetch —
  comportamento já mitigado por design.
- **Mind map — só metadata, tree completa pendente.** 141 mind maps
  capturados em `notebooklm_outputs.parquet`, mas o `content` é só
  metadata (`[mm_uuid, nb_uuid, [timestamp]]`, ~138 chars). A tree
  hierárquica de nodes não está mapeada — o RPC `CYK0Xb` atual retorna
  só metadata. Pra ter tree completa, precisa identificar outro RPC
  via probe Chrome MCP com sessão NotebookLM ativa.
- **Chat real — não é bug, é estado dos dados.** Dos 143 notebooks
  atuais, 0 têm chat populado upstream (user não fez chats reais nos
  notebooks). As 138 messages capturadas são `role=system`
  (`guide.summary` virando seq=0). Quando você fizer chats reais no
  futuro, parser tem placeholder em `_extract_chat_turns()` — pode
  precisar mapear o schema posicional.

### Claude Code (CLI)

- **Não há features de pin/archive/temporary** — são CLI, sem servidor
  com essas semânticas. Os campos ficam `None`.
- **Sem reconciler dedicado:** preservation de arquivos é feita pelo
  `cli-copy.py` (nunca deleta destino). O parser detecta
  `is_preserved_missing=True` comparando `data/raw/Claude Code/` com
  `~/.claude/projects/` atual.
- **Sessões compactadas (`/compact`):** quando você usa `/compact`, a
  thread continua num JSONL novo. O parser identifica e consolida via
  `sessionId` interno (todos os JSONLs viram 1 Conversation com
  `conv_id` = raiz da cadeia).

### Codex (CLI)

- Mesmas observações dos CLIs acima.

### Gemini CLI

- Mesmas observações dos CLIs acima.
- **Snapshots periódicos:** o Gemini CLI grava múltiplos arquivos
  `session-<timestamp>-<sid>.json` para a mesma sessão. O parser
  consolida via `sessionId` com dedup por `message_id`.

## Cobertura de testes

- **514 testes passando.** Cobre parsers (todos os 10), schema canônico,
  helpers de notebook, unify, **reconcilers de todas as 7 plataformas
  web** (smoke tests com fixtures: build_plan + run_reconciliation +
  preservation + idempotência), **funções puras dos 6 extractors web**
  (parsing, dedup, baseline de discovery, target_path, ext_from_url).
- **HTTP/auth/Playwright dos extractors sem teste de unidade.** A lógica
  é validada empiricamente nos syncs reais. Mockar Playwright/httpx é
  caro (~20h de setup + frágil quando a plataforma muda). Caso valha,
  ficar em backlog pra v1.0.

## Limitações operacionais

- **Windows não testado.** macOS e Linux funcionam.
- **Python ≥3.12 requerido** (testado em 3.12 e 3.14).
- **Captura headless (sem janela)** funciona em Claude.ai, Gemini,
  NotebookLM, Qwen, DeepSeek. ChatGPT e Perplexity exigem janela
  visível porque Cloudflare detecta clientes headless e bloqueia com
  HTTP 403.
- **Profile/cookies** ficam em `.storage/<plat>-profile-<conta>/`. Esse
  diretório é gitignored — nunca commitado. Se você apagar, precisa
  refazer o login.
- **Multi-conta:** apenas Gemini (2 contas) e NotebookLM (até 3 contas)
  têm suporte explícito. Outras plataformas: 1 conta por instalação.
