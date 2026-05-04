# Extractor findings — design notes and discovery patterns

This document consolidates non-obvious findings from building the per-platform extractors: API endpoints, edge cases, design decisions, and recurring patterns. The extractors implement these directly; this is the **why and how** behind the code.

For runtime behavior of each platform (CRUD effects, server quirks), see
`docs/platforms/<platform>/server-behavior.md`. For setup, see `docs/SETUP.md`.

---

## ChatGPT

### Shared conversations have two IDs — use `conversation_id`, not `id`

The `/backend-api/shared_conversations` endpoint returns items with **two distinct IDs**:

- `id`: the public **share UUID** (used in `https://chatgpt.com/share/{id}`)
- `conversation_id`: the actual conversation ID, matching `/conversations` (main/archived/projects)

Using `id` in `/backend-api/conversation/{id}` returns HTTP 404 — shares live in separate storage.

**How to apply:** when adding any endpoint that returns shared/public items, inspect raw responses before assuming `id` is the conversation identifier. The same pattern may repeat in other platforms (Claude.ai shares, Gemini shares).

The extractor emits `discovery_ids.json` with every capture, enabling post-hoc diff between discovery and fetched without re-running.

### Voice mode: API returns transcription in `parts`

The single/batch endpoint (`/backend-api/conversation/{id}`) returns full `audio_transcription` for both user and assistant via dicts in `message.content.parts`:

```json
{
  "content_type": "multimodal_text",
  "parts": [
    {"content_type": "real_time_user_audio_video_asset_pointer",
     "audio_asset_pointer": {...}},
    {"content_type": "audio_transcription",
     "direction": "in",
     "text": "..."}
  ]
}
```

`direction: "in"` = user, `direction: "out"` = assistant.

**How to apply:** parsers iterating `parts` must handle both strings and dicts — strings-only iteration silently drops audio transcripts. The DOM-scrape voice fallback (`dom_voice.py`) is therefore redundant in normal capture flow; kept as theoretical fallback.

### Asset download endpoint

Conversation files (images, uploads, DALL-E outputs) are served by:

```
GET /backend-api/files/download/{file_id}
  → {download_url: "https://chatgpt.com/backend-api/estuary/content?id=X&ts=Y&sig=Z&...",
     file_name, mime_type, ...}
```

The returned `download_url` is presigned; a second GET with Bearer auth fetches the bytes.

Works for **both** asset pointer formats found in raw:

- `sediment://file_XXX` (modern, hex IDs)
- `file-service://file-XXX` (legacy, hyphenated)

**Anti-bug:** do **not** confuse with `/backend-api/files/{id}/download` (id+download swapped) — that endpoint returns `permission_error` for everything.

**Why it matters:** earlier attempts via Playwright DOM scraping (intercepting `<img>` tags) hit ~54% success rate due to React virtualization recycling elements before capture, and were ~45s per conversation. The direct API achieves ~98% in seconds.

**Known irrecoverable cases (server-side deletions surface as errors):**

1. **Multi-page PDFs** rendered as `sediment://{hash}#{file_id}#p_{N}.jpg` — parent file_id returns "File not found"; UI confirms "no longer available".
2. **Expired DALL-E images** — `no_download_url` from API; UI fails to load.
3. **Expired screenshots** — perpetual spinner in UI, `no_download_url` from API.

These are documented as expected failures, not bugs.

### Project knowledge files require `?gizmo_id`

Files attached at the **project level** (knowledge base shared across all conversations in a project) need a different endpoint pattern:

```
# 1. List files of a project
GET /backend-api/gizmos/{project_id}
  → response includes `files: [...]` alongside gizmo, tools, product_features
  Schema: {id, file_id, name, type (MIME), size, created_at}

# 2. Get presigned URL for a file
GET /backend-api/files/download/{file_id}?gizmo_id={project_id}
  → {download_url: "..."}

# Without ?gizmo_id:
  → {error_code: "permission_error", error_type: "GetDownloadLinkError"}
```

The query param is **mandatory**. Same `file-XXX` ID format as conversation files, but project-level files are treated as confidential and require gizmo context to authorize.

**How to apply:** project knowledge files are conceptually equivalent to Claude.ai's project `docs[]`. Run `chatgpt-download-project-sources.py` after the main capture when you want full backup of project knowledge bases.

---

## Claude.ai

### Hypothesis: official export filters; API does not

The official export from the Anthropic UI redacts certain fields. The live API (`api.claude.ai`) returns full data — confirmed by comparing the same conversation across both: e.g., `file_uuid` is `null` in the export but a valid UUID with `preview_url` and `thumbnail_url` in the API response.

**Implication:** for completeness and feature recovery (project docs with content, citations, branches, settings), capture via the API rather than relying on official export.

### Endpoints

```
# List conversations (max ~1000 per call; cap on starred=False at ~816)
GET /api/organizations/{org_id}/chat_conversations_v2?limit=N&starred={bool}&consistency=eventual

# Full conversation tree
GET /api/organizations/{org_id}/chat_conversations/{conv_uuid}
    ?tree=True&rendering_mode=messages&render_all_tools=true&consistency=eventual

# Projects
GET /api/organizations/{org_id}/projects
GET /api/organizations/{org_id}/projects/{uuid}           # metadata
GET /api/organizations/{org_id}/projects/{uuid}/docs      # knowledge sources with content
GET /api/organizations/{org_id}/projects/{uuid}/files     # images / PDFs

# Assets — note absence of /organizations/ in the path
GET /api/{org_id}/files/{file_uuid}/preview     # full image
GET /api/{org_id}/files/{file_uuid}/thumbnail   # 400px (also PDF cover)
```

### `file_kind` drives the download variant

The `file_kind` field in the file record decides which endpoint returns useful data:

- `image` → `/preview` (primary) and `/thumbnail` (optional)
- `document` → `/thumbnail` only (renders the first page; original binary is **not exposed**)
- `blob` → not downloadable (`.txt` paste-ins; content is inline in `extracted_content`)

**How to apply:** branch on `file_kind` before hitting endpoints. A blanket loop hitting `/preview` for every file will fail on documents and blobs.

### `org_id` auto-detection

The org_id is captured from the `lastActiveOrg` cookie by `auth.load_context()`. No manual config needed after initial login.

### Cloudflare bypass

Direct curl is blocked. Playwright with `launch_persistent_context` works because it reuses `cf_clearance` / `__cf_bm` from the authenticated session. Headless mode is fine for automation. The `--disable-blink-features=AutomationControlled` flag removes basic automation detection.

When `cf_clearance` expires (typically days to weeks), re-run `claude-login.py`.

---

## Gemini (Google batchexecute)

### Decision: API over DOM scraper

Initial options were (A) reverse-engineer the internal API or (B) refactor an existing DOM scraper. A 1-hour probe confirmed:

- The internal API exists via **batchexecute** (Google's standard, same family as NotebookLM)
- `rpcids` are obfuscated but **stable** (do not change with UI redesigns)
- Both user-uploaded and model-generated images are accessible via presigned URLs

Option A won: 3-10 minutes runtime vs 40 minutes DOM, more stable long-term, and consistent with the architecture of the ChatGPT and Claude.ai extractors.

### Endpoint and protocol

```
POST /_/BardChatUi/data/batchexecute
  ?rpcids=<id>
  &bl=<build>
  &f.sid=<session>
  &hl=en&rt=c&_reqid=<N>

Headers:
  Content-Type: application/x-www-form-urlencoded;charset=UTF-8
  X-Same-Domain: 1

Body:
  f.req=<JSON>&at=<XSRF_TOKEN>
```

### Session params extracted from HTML

Three parameters are scraped from the home page HTML via regex:

- `SNlM0e` → `at` (XSRF token)
- `cfb2h` → `bl` (build label)
- `FdrFJe` → `f.sid` (session id)

Implementation in `batchexecute.py::extract_session_params()`. If they expire mid-run, the API client refreshes via `GeminiAPIClient.refresh_session()`.

### Response envelope

Google batchexecute uses a `)]}'` prefix followed by length-prefixed chunks. Parse with bracket-matching that respects quoted strings (naive splits on commas break on JSON inside strings).

Inner format: `[["wrb.fr", rpcid, "<inner_json_as_string>", null, null, null, "generic"]]`. The inner payload is JSON inside an escaped string.

**Critical formatting:** when sending payloads, use `json.dumps(payload, separators=(',', ':'))` — Google rejects requests with whitespace between separators.

### Core rpcids

| rpcid | Purpose | Payload |
|---|---|---|
| `MaZiqc` | List all conversations | `[]` |
| `hNvQHb` | Full conversation tree (turns + alt responses + image URLs) | `[conv_id, 10, None, 1, [0], [4], None, 1]` |

`MaZiqc` returns the full list in one shot when ≤ ~50 conversations (no pagination needed at typical N=1 scale).

### Discarded rpcids (non-content, can be ignored)

`DYBcR`, `Te6DCf`, `sJBwce`, `maGuAc` (banners/upsell), `otAQ7b` (model list), `cYRIkd` (extensions), `o30O0e` (user profile), `CNgdBe` (NotebookLM cross-product integration — useful when extending), `ESY5D` (feature flags).

### Image extraction and filtering

Images appear in the `hNvQHb` response as `lh3.googleusercontent.com/gg/<presigned>` URLs. Both user uploads and model-generated images come through the same channel.

Apply these exclusion patterns to skip non-content URLs the regex would otherwise match:

- `faviconV2` — citation favicons
- `/lamda/images/` — tool logos (e.g. SynthID)
- `/branding/` — Google product logos (Calendar, Keep)
- `fonts.gstatic.com` — CSS fonts

Implementation in `api_client.py::extract_image_urls()`. Presigned URLs have short TTL (hours) — download promptly after capture.

### Multi-account

One Playwright profile per account in `.storage/gemini-profile-{N}/`. There is **no in-session account switching** — each run loads one profile via `--account N`.

---

## NotebookLM (batchexecute, distinct base from Gemini)

### Endpoint base differs from Gemini

```
POST /_/LabsTailwindUi/data/batchexecute
  ?rpcids={rpcid}
  &source-path=/notebook/{notebook_uuid}   # optional, scopes the request
  &bl={build_label}
  &f.sid={session_id}
  &hl=en&rt=c&_reqid={N}
```

Everything else of the protocol is identical to Gemini's: same `SNlM0e/cfb2h/FdrFJe` session params, same `)]}'` envelope, same `wrb.fr` inner shape. The `batchexecute.py` helpers can be reused with only the URL base swapped.

### Complete rpcid map

| rpcid | Purpose | Payload | Notes |
|---|---|---|---|
| `ub2Bae` | List notebooks of the account | `[[2]]` | Hero page payload |
| `wXbhsf` | Notebook metadata + sources list | `[null, 1, null, [2]]` | Sources with UUID, name, size, timestamps |
| `rLM1Ne` | Basic metadata | `["{nb_uuid}", null, [2], null, 0]` | Subset of `wXbhsf` |
| `VfAZjd` | Guide (auto-generated summary + suggested questions) | `["{nb_uuid}", [2]]` | |
| `khqZz` | Chat history | `["{nb_uuid}", null, null, [2]]` | User-AI conversations |
| `cFji9` | Notes / mind maps / briefs | `["{nb_uuid}", null, null, [2]]` | Mind maps detected by inline JSON heuristic (starts with `{`) |
| `gArtLc` | Generative outputs metadata + URLs | `[[2, null, null, [1, null, ...]]]` | Audio, video, slides, infographics |
| `hizoJc` | **Source content** (extracted text + per-page rendered images) | `[["{source_uuid}"], [2], [2]]` | Critical for content recovery — see below |
| `hPTbtc` | Mind map UUID | `[[], null, "{nb_uuid}", 20]` | Returns UUID if a mind map exists |

Settings/UI rpcids (`JFMDGd`, `ZwVcOc`, `ozz5Z`, `sqTeoe`, `e3bVqc`) are non-content and can be ignored.

### `hizoJc`: source content extraction

NotebookLM acts as RAG: original PDFs/uploads are **not exposed** — only the text-extracted version with rendered page images. `hizoJc` returns this content chunk-by-chunk:

```json
[
  [["{source_uuid}"], "filename.pdf", [null, size_bytes, [ts, ns], ...]],
  null, null,
  [[[
    [0, 1, [[[0, 1, null, ["https://lh3.../page_image", null, "{page_uuid}"]]]]],
    [2, 34, [[[2, 34, ["TCC text..."]]], [null, 4]]],
    ...
  ]]]
]
```

Each chunk is `[start_offset, end_offset, [[[start, end, [...payload]]], [null, style_hint]]]`:

- Chunks with text in `payload[0]` are extracted text
- Chunks with a URL in `payload[3][0]` are rendered page images
- `style_hint` (4 = h2, 6 = h3 — empirical) helps reconstruct hierarchy

**How to apply:** sort chunks by `start_offset` and concatenate text, keeping page-image chunks separately for download. This is the only way to recover what the model "sees" of the sources.

### Generative outputs (9 types)

Returned by `gArtLc`. Each type has its own retrieval pattern:

| UI label | `gArtLc` type | Format | Retrieval |
|---|---|---|---|
| Audio Overview | 1 | m4a | URL `lh3` in `ao[6][2]`, direct download |
| Blog Post / Report | 2 | JSON text | Fetch via `v9rmvd` by UUID |
| Video Overview | 3 | mp4 | URL `lh3` in `ao[8][1]`, direct download |
| Flashcards / Quiz | 4 | JSON | Fetch via `v9rmvd` |
| Data Table | 7 | JSON | Fetch via `v9rmvd` |
| Slide Deck | 8 | PDF + PPTX | URLs `contribution.usercontent.google.com` in `ao[16][-2]` (PDF), `ao[16][-1]` (PPTX) |
| Infographic | 9 | JSON | Fetch via `v9rmvd` |

**Mind Map** does **not** come via `gArtLc`. It arrives inline in `cFji9` (notes payload) as a JSON string of shape `{"name": ..., "children": [...]}`. Detect by heuristic: payload starts with `{`.

**Anti-bug:** type=8 was initially confused with Audio Overview because the first URL extracted was an embedded thumbnail PNG. The actual binary (PDF/PPTX) is at the **end** of `ao[16]` — adjust your URL extractor to pick the right index by file magic bytes (`%PDF`, `PK..`).

### Audio download via redirects

URLs from `gArtLc` (`lh3.googleusercontent.com/notebooklm/{token}`) redirect twice: first to `rd-notebooklm`, then to `rr1---sn-*.googlevideo.com/videoplayback?...`. Cookies from the authenticated Playwright session must accompany the request. Default Playwright timeout (30s) is too short — use 120s+ for audio/video downloads.

### "Touched but unchanged" — `update_time` is volatile

Opening a notebook in the UI bumps `update_time` on the server **even without user changes**. Using `update_time` alone as a "did this change?" signal causes spurious full re-fetches.

The mitigation in the extractor: a **lite-fetch pass** before deciding to full-fetch. For each discovered notebook, fetch 3 cheap RPCs (`rLM1Ne` + `cFji9` + `gArtLc`) in parallel and compare with the previous raw using a lenient equality (ignoring volatile timestamps and `None`-vs-value differences):

- Equal under lenient comparison → copy notebook + sources from previous raw, no full fetch
- Different → full fetch

Documented in `notebooklm/orchestrator.py`. Trade-off: notebooks merely opened in the UI fall into full-fetch unnecessarily — accepted as the cost of safety.

---

## Cross-cutting patterns

### Reconciler enrichment propagation (`build_plan` design)

Reconcilers compare current raw vs previous merged to decide which version of each conversation to keep. A naive criterion — `update_time` only — silently drops local enrichment fields injected by the orchestrator (`_project_name`, `_project_id`, `_archived`, `_truncation_recovered`, etc.).

Why: enrichment fields (the `_*` prefix) do not exist in the raw API response. They are added by the orchestrator after fetch. They do **not** alter `update_time`. If the reconciler only looks at `update_time`, a re-run that adds new enrichment to existing conversations will keep the old merged record without the enrichment.

**Two combined rules fix this:**

1. Compare `_*` fields in addition to `update_time` (so new enrichment propagates)
2. Exclude **operational** `_*` fields from the comparison (so reconcile doesn't become a full rewrite on every run)

```python
# src/reconcilers/<source>.py

# Operational _* fields (change every capture even when nothing else did).
# Excluded from semantic enrichment comparison.
OPERATIONAL_ENRICHMENT = {"_last_seen_in_server"}

# Inside build_plan:
curr_enrich = {k: v for k, v in curr.items()
               if k.startswith("_") and k not in OPERATIONAL_ENRICHMENT}
prev_enrich = {k: v for k, v in prev.items()
               if k.startswith("_") and k not in OPERATIONAL_ENRICHMENT}
if curr_ut > prev_ut or curr_enrich != prev_enrich:
    to_use.append(cid)
else:
    to_copy.append(cid)
```

**Why blacklist (not whitelist):** the default behavior should be "propagate new info". A whitelist creates silent bugs: adding a new semantic field and forgetting to register it means it never propagates, and nobody notices until they open the parquet. A blacklist inverts the default: new fields propagate unless explicitly marked operational.

**Criterion for blacklisting a field:** does this field change every capture without the conversation having changed? Examples of operational: `_last_seen_in_server`, `_capture_timing`, `_retry_count`, `_fetch_duration`. Examples of semantic (do **not** blacklist): `_project_name`, `_archived`.

**Required tests** when adding a reconciler:

- Semantic enrichment differs → should land in `to_use`
- Semantic enrichment equal → should land in `to_copy`
- Only operational diff with semantic equal → should still land in `to_copy`

When two or more reconcilers exist, factor the helper into `src/reconcilers/base.py` with a per-source-parametrizable blacklist.

### Incremental capture: detect previous run automatically

Each extractor's orchestrator scans `data/raw/<Source> Data <date>/*` for prior captures (with `capture_log.json` + raw payload) and uses the most recent `run_started_at` as cutoff. Behavior:

- No previous capture → full discovery + fetch
- Previous capture present → fetch only conversations with `update_time > cutoff`, copy others from previous raw with `_last_seen_in_server` updated
- `--full` flag → force full re-fetch regardless of previous state (periodic sanity check)

The final raw always contains **all** conversations (the reconciler contract is preserved). This applies to all platforms with `capture_log.json` instrumentation.

**Limitation:** discovery itself cannot be incremental for most platforms — there is no "give me only changed IDs" endpoint, so listing the universe takes its full time on every run.

### Cookie persistence vs Bearer auth

Two authentication models in use:

- **Bearer token** (ChatGPT): obtained from `/api/auth/session` → `accessToken` field, sent as `Authorization: Bearer {token}` header. Refreshed by re-running login when expired.
- **Cookie context** (Claude.ai, Gemini, NotebookLM, Perplexity, others): Playwright's `launch_persistent_context` reuses the storage from the initial login. For platforms behind Cloudflare (Claude.ai), cookies include `cf_clearance` which is what allows headed and headless requests to pass.

The login script for each platform persists this state to `.storage/<platform>-profile[-{account}]/`. Login runs are interactive (browser visible); subsequent capture runs are headless except for ChatGPT and Perplexity (Cloudflare detects headless without a window — see SETUP.md).

---

## Known parser limitations / future work

### Claude Code: image base64 inline

Claude Code stores user-attached images **inline as base64** in the JSONL session files (`content[].source.data` in `type=image` blocks). Current parser does not handle `type=image` — only `text`, `tool_use`, `tool_result`, `thinking`. As a result:

- Hundreds of images per session can be present in raw but invisible in the unified parquet
- `~/.claude/image-cache/` is **not** authoritative — it is a UI-disposable cache. Use the JSONL inline data.

When implementing: in the content-block loop, detect `type == "image"`, decode base64 from `source.data`, infer extension from `source.media_type` (`image/jpeg` → `.jpg`), save to `data/raw/Claude Code Data/_images/{session_id}/{msg_seq}_{block_idx}.{ext}`, and register the path in `attachment_names` of the `Message`.

Other Claude Code fields currently dropped by the parser:

- `message.usage` (token counts per message)
- `gitBranch`, `cwd`, `permissionMode` (per-session operational context — useful for cross-project analysis)
- `attachment` records (separate from image blocks)

### Codex: `context_compacted` events

Codex has a specific `event_msg` type — `context_compacted` — that is currently captured generically. This connects to the broader topic of context fragmentation and could be promoted to a first-class event in the schema.
