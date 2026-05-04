# Per-platform checkpoints (cross-feature checks)

When we discover a feature on one platform (pin, archive, voice, share),
**check empirically on the others** to see if it also exists and whether the extractor
captures it. List grows as we learn.

## Pin

| Platform | Status | How |
|---|---|---|
| Perplexity | ✅ thread | `list_pinned_ask_threads`, field `is_pinned: true`. Canonical schema: `Conversation.is_pinned`. Validated 2026-05-01. |
| ChatGPT (conv) | ✅ | Fields `is_starred` and `pinned_time` in the raw schema (UI: "Pin" in the menu). NO dedicated endpoint — comes in the normal payload of `/conversations` and `/conversation/{id}`. Parser maps `is_starred` → `Conversation.is_pinned`. Validated 2026-05-01 via Chrome MCP probe. |
| ChatGPT (gizmo) | ✅ | Endpoint `/backend-api/gizmos/pinned` returns the list. Captured in `data/raw/ChatGPT/gizmos_pinned.json` (sidecar). |
| Claude.ai | ✅ | `is_starred` (pin) + `is_temporary` in the API schema (`/api/organizations/{org}/chat_conversations_v2`). Parser v3 maps both: 12 pinned out of 834 convs; `is_temporary` preserved in-place (0 captured — ephemeral feature). No `is_archived` field visible in the schema. |
| Qwen | ✅ | `pinned` → `is_pinned`. Validated 2026-05-01. |
| DeepSeek | ✅ | `pinned` → `is_pinned`. Validated 2026-05-01. |
| Gemini | ✅ | Pin discovered via probe — field `c[2]` of the MaZiqc listing returns `True` when pinned. Validated 2026-05-02. |
| NotebookLM | ⚠️ N/A | Feature does not exist upstream (confirmed in the app). |

## Thread/conv archive

| Platform | Status |
|---|---|
| Perplexity | ⚠️ Enterprise-only. Backend accepts `archive_thread`/`unarchive_thread` but state is not exposed via the public API on a Pro account. No gap. |
| ChatGPT | ✅ raw schema has `is_archived` + `_archived`. UI has an Archive option. Currently 0 archived convs out of 1168 (feature works, just not used). **TODO:** when the user archives, validate reconciler + parser. |
| Qwen | ⚠️ no-op upstream on Pro/free — server accepts the request, the `archived` flag never persists, endpoint `/v2/chats/archived` returns `len=0`. Same pattern as Perplexity Enterprise-only. Canonical schema has `is_archived`, just never True. |
| DeepSeek | ⏸ to verify. |
| Claude.ai | ⏸ no `is_archived` field visible. |
| Gemini | ⏸ to verify. |
| NotebookLM | ⏸ to verify. |

## Share URL

| Platform | Status |
|---|---|
| Gemini | ⚠️ upstream-only — server generates an isolated public URL (`gemini.google.com/share/<id>`), does NOT modify the chat body or fields in the listing. Not an extractor gap. Validated 2026-05-02. |

## Voice

| Platform | Status |
|---|---|
| ChatGPT | ✅ `direction in/out` captured, parser records it in Message. |
| Perplexity | ⚠️ not-a-bug, upstream behavior (server transcribes and discards audio, no `is_voice` in the schema). |
