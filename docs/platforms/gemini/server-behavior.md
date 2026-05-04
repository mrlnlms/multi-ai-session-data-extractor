# Gemini — server behavior (empirically validated)

Initial probe on 2026-05-02 over **80 convs** (47 account-1 + 33 account-2)
captured via batchexecute (rpcids `MaZiqc` list + `hNvQHb` fetch).

## Volume and coverage

| Account | Convs | Images dl | Deep Research | Total assets |
|---|---|---|---|---|
| account-1 | 47 | 126 | ~6 (extracted) | 172 |
| account-2 | 33 | 89 | 12 (extracted) | 113 |
| **Total** | **80** | **215** | **~18** | **285** |

## Raw schema — positional (no keys)

Paths discovered via probe (`scripts/gemini-probe-schema.py`):

```
raw                 — list[4] = [turns_wrapper, ?, None, ?]
raw[0]              — list of turns
raw[0][i]           — turn = [ids, response_ids, user_msg, response_data, ts]
raw[0][i][0]        — [conv_id, response_id]
raw[0][i][1]        — [conv_id, resp_id_a, resp_id_b]  (alternatives/drafts)
raw[0][i][2]        — user message: [[user_text], turn_seq, null, ...]
raw[0][i][3]        — response data (25 fields)
raw[0][i][3][0][0]  — main response: [resp_id, [text_chunks], ..., thinking_data]
raw[0][i][3][8]     — locale (e.g. 'BR')
raw[0][i][3][21]    — model name (e.g. '2.5 Flash', '3 Pro', 'Nano Banana')
raw[0][i][4]        — [created_at_secs, microseconds]
```

## Detected models (Gemini-side display names)

| Model | Convs (last seen) | Msgs |
|---|---|---|
| 2.5 Flash | 35 | 118 |
| 3 Pro | 21 | 81 |
| Nano Banana | 6 | 33 |
| 3 Flash Thinking | 6 | 21 |
| 3 Flash | 4 | 9 |
| Nano Banana Pro | 1 | 7 |
| Nano Banana 2 | 1 | 3 |
| 2.5 Pro | 1 | 1 |

`Nano Banana` = codename for Gemini image generation (Flash 2.0/2.5 Image).
`3 Flash Thinking` = model with visible reasoning.

## Observed features

- ✅ **Multi-account:** 2 distinct Google accounts, separate profiles
  (`.storage/gemini-profile-{1,2}/`). Each account may have a disjoint set
  of convs.
- ✅ **Thinking blocks** in `resp[0][0][37+]` — nested array of strings.
  Extraction heuristic: blocks >=200 chars that do NOT appear in the
  main response. **41% of assistant msgs have thinking** (116/280).
- ✅ **Image generation** via Nano Banana — URLs in
  `lh3.googleusercontent.com/gg/...` (presigned). **215 images** downloaded
  via asset_downloader. Resolved in `Message.asset_paths` via
  `assets_manifest.json`.
- ✅ **Deep Research** — markdown reports generated. Extracted OFFLINE by
  asset_downloader (sweeps raw, detects strings >2500 chars that look like
  a markdown report). **~18 reports** extracted.
- ✅ **Locale** in `resp[8]` (e.g. 'BR') — preserved in `settings_json`.
- ✅ **Sharing** — ~16 convs with substring 'share' in the JSON (URLs
  `g.co/gemini/share/...`). Not surfaced in canonical schema v3 — TODO
  structural probe.

## Schema limitations (vs ChatGPT/Claude.ai)

- ❌ **No `updated_at`** — Gemini only exposes `created_at_secs`. Parser uses
  `max(turn timestamps)` as a proxy. Implication: new msgs in an existing
  conv do NOT bump the discovery timestamp — `--full` is necessary to force
  refetch in those cases.
- ❌ **No `pinned`/`archived` flags** detected in the raw schema or in
  discovery. Gemini probably doesn't have these features (or they're in a
  separate, unmapped endpoint).
- ❌ **Branches/drafts** — `raw[0][i][1]` has 2 alternating response_ids
  (likely multi-draft), but the structure is still not mapped. **Not surfaced
  in v3** (few cases detected).
- ✅ **Search/grounding citations** — extracted via
  `extract_turn_citations()` in `_gemini_helpers.py` (probe 2026-05-04).
  Positional pattern `[favicon, source_url, title, snippet, ...]` where
  favicon contains `gstatic.com/faviconV2`. Result: 416 structured
  search_results in 9 messages (Search/Deep Research) — populated in
  `Message.citations_json` + ToolEvents of type `search_result`.
- ❌ **Voice / TTS audio** — likely `resp[12]` (audio chunks?), not
  identified in probe.

## Bugs found during migration (preventive vs Qwen+DeepSeek)

The same 3 patterns from Qwen/DeepSeek applied preventively to Gemini:

1. **`_get_max_known_discovery(output_dir)`** (not `parent`) — avoids
   leakage across platforms.
2. **`discover()` lazy persist** (separate from `persist_discovery()`) —
   ensures fail-fast does not corrupt the incremental baseline.
3. **`--full` propagated to reconcile** in `gemini-sync.py`.

Plus:
4. **Multi-account** — orchestrator/reconciler operate per-account; the sync
   orchestrator (`gemini-sync.py`) iterates over both. `account-{N}/`
   subfolders in raw and merged.
5. **Adapted dashboard** — `_collect_logs()` now supports both flat layout
   (`base/capture_log.jsonl`) and multi-account
   (`base/account-*/capture_log.jsonl`).

## Observed behavior

- **Discovery:** the `MaZiqc` rpc returns a paginated list with `[uuid, title,
  created_at_secs]`. Stable across consecutive probes.
- **Fetch transient errors:** the first run on account-1 had 18 fetches returning
  None (likely batchexecute rate limit). The incremental retry picked them
  all up cleanly. **`fetch_conversations` has no built-in retry** —
  consider adding exponential backoff in a future iteration.
- **`hNvQHb` payload:** `[conv_uuid, 10, None, 1, [0], [4], None, 1]` —
  functional in 2026-05-02. The rpcid hash may change — fail-fast covers it.

## UI CRUD battery — 2026-05-02 (account-1, hello.marlonlemes@gmail.com)

User executed 4 actions in the UI. 4/4 scenarios covered:

| Action | Chat | Parquet result | Notes |
|---|---|---|---|
| Rename → "Benchmarks Smiles Gol Pesqusias" | `c_dc5c683537a19cd1` | ✅ title matches | `created_at_secs` does NOT bump on rename — uses title-diff in the reconciler |
| Pin → "Análise de Dados da Cota Parlamentar" | `c_98c60a18de056385` | ✅ `is_pinned=True` | Pin flag in `c[2]` of the MaZiqc listing (discovered via probe) |
| Delete | `c_b17426c13c5e1bc3` | ✅ `is_preserved_missing=True` | Title + last_seen preserved |
| Share URL generated (`/share/c2a6a6436942`) | n/a | ✅ confirmed upstream-only | Server does NOT modify body, listing, or chat fields — share generates an isolated public URL |

## Pin discovered via probe

The MaZiqc listing schema has 10 fields per conv:
```
[0] conv_id      (str)
[1] title        (str)
[2] pinned       (True or None)   ← FLAG DISCOVERED
[5] [secs, nanos] timestamp
[9] int          (always 2 in this base)
```

Probe: `scripts/gemini-probe-pin-share.py`. Comparison between a pinned chat
and normal chats revealed a difference in position [2]. Alternative RPC ids
tested (EaipR, yQzmHb, VhQOs) returned 400 — pin has no dedicated endpoint
(same as ChatGPT, which also doesn't expose a separate `/pinned` but uses a
flag in the listing body).

## Additional bugs found+fixed in the battery

4. **Orchestrator did not pass `skip_existing=False`** to the fetcher —
   `--full` mode still skipped local bodies and didn't capture server changes.
   Same pattern as the original Qwen. Fix: `skip_existing=False` when
   `to_fetch` was already filtered by the orchestrator.
5. **Discovery extractor did not capture `pinned`** (field `c[2]`) — added
   in `list_conversations()` + `persist_discovery()` + reconciler `build_plan`
   detects `pinned_changed` as an update signal.

## Server behavior (validated 2026-05-02)

- **Rename:** `created_at_secs` does NOT bump. Detection is via title-diff
  in the reconciler. Local body stays stale until `--full` or title detection.
- **Pin:** flag in `c[2]` of the listing immediately after the action. Bumps
  some internal timestamp? Not detectable via current fields.
- **Delete:** chat disappears from listing → reconciler marks
  `_preserved_missing`, `last_seen_in_server` preserves the previous date,
  raw body is preserved.
- **Share:** generates a public URL at `gemini.google.com/share/<id>`. Does
  NOT modify the chat body, does NOT add a field to the listing. The URL is
  "outside" the chat schema — an export feature, not state. **Not an
  extractor gap.**

## Residual pending items (non-blocking)

- [ ] **Branches/drafts** (`raw[0][i][1]` with 2 response_ids) — structure
  not mapped, rare cases detected.
- [ ] **Search/grounding citations** — 1/80 convs with 'grounding' substring,
  structure not mapped.
- [ ] **Add to notebook** — NotebookLM integration, not tested.
