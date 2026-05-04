# Pontos de verificacao por plataforma (cross-feature checks)

Quando descobrimos uma feature numa plataforma (pin, archive, voice, share),
**checar empiricamente nas outras** se ela tambem existe e se o extractor
captura. Lista crescente conforme aprendemos.

## Pin

| Plataforma | Status | Como |
|---|---|---|
| Perplexity | ✅ thread | `list_pinned_ask_threads`, campo `is_pinned: true`. Schema canonico: `Conversation.is_pinned`. Validado 2026-05-01. |
| ChatGPT (conv) | ✅ | Campos `is_starred` e `pinned_time` no schema raw (UI: "Pin" no menu). NAO existe endpoint dedicado — vem no payload normal de `/conversations` e `/conversation/{id}`. Parser mapeia `is_starred` → `Conversation.is_pinned`. Validado 2026-05-01 via probe Chrome MCP. |
| ChatGPT (gizmo) | ✅ | Endpoint `/backend-api/gizmos/pinned` retorna lista. Capturado em `data/raw/ChatGPT/gizmos_pinned.json` (sidecar). |
| Claude.ai | ✅ | `is_starred` (pin) + `is_temporary` no schema da API (`/api/organizations/{org}/chat_conversations_v2`). Parser v3 mapeia ambos: 12 pinadas em 834 convs; `is_temporary` preservado in-place (0 capturadas — feature efemera). Sem campo `is_archived` no schema visivel. |
| Qwen | ✅ | `pinned` → `is_pinned`. Validado 2026-05-01. |
| DeepSeek | ✅ | `pinned` → `is_pinned`. Validado 2026-05-01. |
| Gemini | ✅ | Pin descoberto via probe — campo `c[2]` do listing MaZiqc retorna `True` quando pinado. Validado 2026-05-02. |
| NotebookLM | ⚠️ N/A | Feature nao existe upstream (confirmado no app). |

## Archive de thread/conv

| Plataforma | Status |
|---|---|
| Perplexity | ⚠️ Enterprise-only. Backend aceita `archive_thread`/`unarchive_thread` mas estado nao expoe via API publica em conta Pro. Sem gap. |
| ChatGPT | ✅ schema raw tem `is_archived` + `_archived`. UI tem opcao Archive. Atualmente 0 convs arquivadas em 1168 (feature funciona, so nao usada). **TODO:** quando user arquivar, validar reconciler + parser. |
| Qwen | ⚠️ no-op upstream em Pro/free — servidor aceita request, flag `archived` nunca persiste, endpoint `/v2/chats/archived` retorna `len=0`. Mesmo padrao do Perplexity Enterprise-only. Schema canonico tem `is_archived`, so nunca True. |
| DeepSeek | ⏸ verificar. |
| Claude.ai | ⏸ sem campo `is_archived` visivel. |
| Gemini | ⏸ verificar. |
| NotebookLM | ⏸ verificar. |

## Share URL

| Plataforma | Status |
|---|---|
| Gemini | ⚠️ upstream-only — servidor gera URL publica isolada (`gemini.google.com/share/<id>`), NAO modifica body do chat nem campos do listing. Nao eh gap do extractor. Validado 2026-05-02. |

## Voice

| Plataforma | Status |
|---|---|
| ChatGPT | ✅ `direction in/out` capturado, parser registra em Message. |
| Perplexity | ⚠️ nao-bug, comportamento upstream (servidor transcreve e descarta audio, sem `is_voice` no schema). |
