# Gemini — comportamento do servidor (validado empiricamente)

Probe inicial em 2026-05-02 sobre **80 convs** (47 conta-1 + 33 conta-2)
capturadas via batchexecute (rpcids `MaZiqc` list + `hNvQHb` fetch).

## Volume e cobertura

| Conta | Convs | Imagens dl | Deep Research | Total assets |
|---|---|---|---|---|
| account-1 | 47 | 126 | ~6 (extracted) | 172 |
| account-2 | 33 | 89 | 12 (extracted) | 113 |
| **Total** | **80** | **215** | **~18** | **285** |

## Schema raw — posicional (sem keys)

Caminhos descobertos via probe (`scripts/gemini-probe-schema.py`):

```
raw                 — list[4] = [turns_wrapper, ?, None, ?]
raw[0]              — list de turns
raw[0][i]           — turn = [ids, response_ids, user_msg, response_data, ts]
raw[0][i][0]        — [conv_id, response_id]
raw[0][i][1]        — [conv_id, resp_id_a, resp_id_b]  (alternativas/drafts)
raw[0][i][2]        — user message: [[user_text], turn_seq, null, ...]
raw[0][i][3]        — response data (25 fields)
raw[0][i][3][0][0]  — main response: [resp_id, [text_chunks], ..., thinking_data]
raw[0][i][3][8]     — locale (e.g. 'BR')
raw[0][i][3][21]    — model name (e.g. '2.5 Flash', '3 Pro', 'Nano Banana')
raw[0][i][4]        — [created_at_secs, microseconds]
```

## Modelos detectados (Gemini-side display names)

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

`Nano Banana` = codename do image generation Gemini (Flash 2.0/2.5 Image).
`3 Flash Thinking` = modelo com reasoning visivel.

## Features observadas

- ✅ **Multi-conta:** 2 contas Google distintas, profiles separados
  (`.storage/gemini-profile-{1,2}/`). Cada conta pode ter conjunto disjunto
  de convs.
- ✅ **Thinking blocks** em `resp[0][0][37+]` — array nested de strings.
  Heuristica de extracao: blocos >=200 chars que NAO aparecem no
  main response. **41% das assistant msgs tem thinking** (116/280).
- ✅ **Image generation** via Nano Banana — URLs em
  `lh3.googleusercontent.com/gg/...` (presigned). **215 imagens** baixadas
  via asset_downloader. Resolvidas em `Message.asset_paths` via
  `assets_manifest.json`.
- ✅ **Deep Research** — markdown reports gerados. Extraidos OFFLINE pelo
  asset_downloader (varre raw, detecta strings >2500 chars que parecem
  markdown report). **~18 reports** extraidos.
- ✅ **Locale** em `resp[8]` (e.g. 'BR') — preservado em `settings_json`.
- ✅ **Sharing** — ~16 convs com substring 'share' no JSON (URLs
  `g.co/gemini/share/...`). Nao surfaced no schema canonico v3 — TODO probe
  estrutural.

## Limitacoes do schema (vs ChatGPT/Claude.ai)

- ❌ **Sem `updated_at`** — Gemini so expoe `created_at_secs`. Parser usa
  `max(turn timestamps)` como proxy. Implicacao: msgs novas em conv
  existente NAO bumpam timestamp do discovery — uso de `--full` necessario
  pra forcar refetch nesses casos.
- ❌ **Sem `pinned`/`archived` flags** detectados no schema raw nem no
  discovery. Provavelmente Gemini nao tem essas features (ou estao em
  endpoint separado nao mapeado).
- ❌ **Branches/drafts** — `raw[0][i][1]` tem 2 response_ids alternados
  (provavel multi-draft), mas estrutura ainda nao mapeada. **Nao surfaced
  na v3** (poucos casos detectados).
- ❌ **Search/grounding citations** — 1/80 convs com 'grounding' substring,
  estrutura nao mapeada. TODO probe.
- ❌ **Voice / TTS audio** — provavel `resp[12]` (audio chunks?), nao
  identificado em probe.

## Bugs descobertos durante migracao (preventivos vs Qwen+DeepSeek)

Mesmos 3 padroes do Qwen/DeepSeek aplicados preventivamente em Gemini:

1. **`_get_max_known_discovery(output_dir)`** (nao `parent`) — evita
   vazamento entre plataformas.
2. **`discover()` lazy persist** (separado de `persist_discovery()`) —
   garante que fail-fast nao corrompa baseline incremental.
3. **`--full` propagado pro reconcile** em `gemini-sync.py`.

Plus:
4. **Multi-conta** — orchestrator/reconciler operam per-account; sync
   orchestrador (`gemini-sync.py`) itera ambas. Subpastas `account-{N}/`
   em raw e merged.
5. **Dashboard adaptado** — `_collect_logs()` agora suporta tanto layout
   flat (`base/capture_log.jsonl`) quanto multi-account
   (`base/account-*/capture_log.jsonl`).

## Comportamento observado

- **Discovery:** `MaZiqc` rpc retorna lista paginada com `[uuid, title,
  created_at_secs]`. Estavel em probes consecutivos.
- **Fetch transient errors:** primeira run em conta-1 teve 18 fetches retornando
  None (provavel rate limit do batchexecute). Retry incremental pegou
  todos limpos. **`fetch_conversations` nao tem retry built-in** —
  considerar adicionar exponential backoff em iteracao futura.
- **`hNvQHb` payload:** `[conv_uuid, 10, None, 1, [0], [4], None, 1]` —
  funcional em 2026-05-02. Hash do rpcid pode mudar — fail-fast cobre.

## Bateria CRUD UI — 2026-05-02 (account-1, hello.marlonlemes@gmail.com)

User executou 4 acoes na UI. 4/4 cenarios cobertos:

| Acao | Chat | Resultado parquet | Notas |
|---|---|---|---|
| Rename → "Benchmarks Smiles Gol Pesqusias" | `c_dc5c683537a19cd1` | ✅ title bate | `created_at_secs` NAO bumpa em rename — usa title-diff no reconciler |
| Pin → "Análise de Dados da Cota Parlamentar" | `c_98c60a18de056385` | ✅ `is_pinned=True` | Pin flag em `c[2]` do listing MaZiqc (descoberto via probe) |
| Delete | `c_b17426c13c5e1bc3` | ✅ `is_preserved_missing=True` | Title + last_seen preservados |
| Share URL gerada (`/share/c2a6a6436942`) | n/a | ✅ confirmado upstream-only | Servidor NAO modifica body, listing nem campos do chat — share gera URL publica isolada |

## Pin descoberto via probe

Schema do listing MaZiqc tem 10 fields per conv:
```
[0] conv_id      (str)
[1] title        (str)
[2] pinned       (True ou None)   ← FLAG DESCOBERTO
[5] [secs, nanos] timestamp
[9] int          (sempre 2 nesta base)
```

Probe: `scripts/gemini-probe-pin-share.py`. Comparacao entre chat pinado e
chats normais revelou diferenca em posicao [2]. RPC ids alternativos
testados (EaipR, yQzmHb, VhQOs) retornaram 400 — pin nao tem endpoint
dedicado (igual ChatGPT que tambem nao expoe `/pinned` separado mas usa
flag no body do listing).

## Bugs adicionais descobertos+fixados na bateria

4. **Orchestrator nao passava `skip_existing=False`** pro fetcher — `--full`
   mode ainda pulava bodies locais e nao capturava mudancas de servidor.
   Mesmo padrao do Qwen original. Fix: `skip_existing=False` quando
   `to_fetch` ja foi filtrado pelo orchestrator.
5. **Discovery extractor nao captava `pinned`** (campo `c[2]`) — adicionado
   em `list_conversations()` + `persist_discovery()` + reconciler `build_plan`
   detecta `pinned_changed` como signal de update.

## Comportamento de servidor (validado 2026-05-02)

- **Rename:** `created_at_secs` NAO bumpa. Detection eh via title-diff no
  reconciler. Body local fica stale ate `--full` ou title detection.
- **Pin:** flag em `c[2]` do listing imediatamente apos action. Bumpa
  algum timestamp interno? Nao detectavel via campos atuais.
- **Delete:** chat some do listing → reconciler marca `_preserved_missing`,
  `last_seen_in_server` preserva data anterior, body do raw eh preservado.
- **Share:** gera URL publica em `gemini.google.com/share/<id>`. NAO
  modifica body do chat, NAO adiciona campo no listing. URL eh "fora" do
  schema do chat — feature de export, nao de estado. **Nao eh gap do
  extractor.**

## Pendencias residuais (nao bloqueantes)

- [ ] **Branches/drafts** (`raw[0][i][1]` com 2 response_ids) — estrutura
  nao mapeada, raros casos detectados.
- [ ] **Search/grounding citations** — 1/80 convs com 'grounding' substring,
  estrutura nao mapeada.
- [ ] **Add to notebook** — integracao com NotebookLM, nao testada.
