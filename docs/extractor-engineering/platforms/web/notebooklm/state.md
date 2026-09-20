# NotebookLM — technical coverage

NotebookLM is not a pure chat: each notebook is a workspace that produces up
to 9 types of outputs (audio, blog, video, flashcards, quiz, data table,
slide deck PDF+PPTX, infographic, mind map).

## Pipeline

- **Multi-account** — three compatibility-default active accounts (acc-1,
  acc-2, acc-3). Profiles in `.storage/notebooklm-profile-<key>/` (generated via
  `python -m src.platforms.notebooklm.commands.login`).
- **Single cumulative folder per-account:** `data/raw/NotebookLM/account-{N}/`
  and `data/merged/NotebookLM/account-{N}/`.
- **Sync orchestrator (3 steps multi-account):**
  `python -m src.platforms.notebooklm.commands.sync` — capture per-account + assets + reconcile
  per-account.
- Without `--account`, sync still visits `1`, `2`, `3` in that order. An
  explicit `--account <safe-key>` supports a dynamically named local account;
  archive keys and path-like values are rejected.
- **Headless capture.**
- **Historical archive** — immutable old-format snapshots live in
  `data/external/notebooklm-snapshots/<archive>-YYYY-MM-DD/`. The official
  `parse.py` converts them alongside all current merged accounts; they are not
  manual saves and require no live login.

## Outputs e tabelas auxiliares

Os nove tipos observados sao audio overview, blog post, video overview,
flashcards/quiz, data table, slide deck (PDF + PPTX), infographic, mind map e
os artefatos associados ao notebook. Alem das quatro tabelas canonicas, o
parser produz `notebooklm_sources`, `notebooklm_source_guides`,
`notebooklm_notes`, `notebooklm_outputs`, `notebooklm_guide_questions`,
`notebooklm_assets` e `notebooklm_asset_links`.
Essa combinacao e particular do NotebookLM; detalhes de schema e RPC ficam na
[discovery](discovery.md).

### Reference volume (sample corpus)

- acc-1: 130 notebooks / 1,499 sources.
- acc-2: 55 notebooks / 207 sources.
- acc-3: 3 notebooks / 36 sources / 79 page images + 6 notes + 3 mind maps;
  two audio URLs returned upstream HTTP errors during its first sync
  (2026-09-12).

## Mapped RPCs (api_client + fetcher)

- `wXbhsf` — list notebooks.
- `rLM1Ne` — metadata.
- `VfAZjd` — notebook guide.
- `khqZz` — chat (None in most cases).
- `cFji9` — notes.
- `gArtLc` — artifacts (9 types).
- `v9rmvd` — individual artifact content (types 2/4/7/9).
- `CYK0Xb` — mind_map tree (payload `[nb_uuid, mm_uuid]`).
- `hPTbtc` — mind_map UUID.
- `hizoJc` — source content.
- `tr032e` — source guide (discovered via Chrome MCP probe + headed
  Playwright; payload `[[[[source_uuid]]]]`).

## Reconciler v3 (FEATURES_VERSION=2)

Full per-account preservation, single cumulative folder (no dated
subfolders), `LAST_RECONCILE.md` + `reconcile_log.jsonl` per-account.

## Canonical parser

Current account trees and historical archives resolve immutable catalog UUIDs
into `account_id`; legacy labels and all existing native IDs remain unchanged.

`src/platforms/notebooklm/parser.py` + `_parser_helpers.py`. Full rewrite.
**11 parquets** (4 canonical + 7 auxiliary):

- **Canonical:** conversations / messages / tool_events / branches.
- **Auxiliary:** sources / source_guides / notes (kind ∈ {note, brief}) /
  outputs (covers 8 of the 9 types + `mind_map=10`) / guide_questions /
  assets / asset_links.

The asset graph indexes only preserved files: rendered source pages link to
their `source` with role `context`, while generated audio, video, slide-deck,
and historical binaries link to their authoritative `output`
with role `output`. Multi-file slide decks use deterministic child asset IDs;
signed upstream URLs and text-only domain records are not assets.

The extractor also materializes text-bearing artifacts under `assets/`: note
Markdown, mind-map JSON trees and JSON envelopes returned by the text-artifact
RPC. Although the local serialization is produced by the pipeline, each file
preserves an identifiable user-facing NotebookLM object. All are indexed as
Assets and linked to their exact `note` or `output` object.

Note metadata type 1 identifies a user-created/editable note; type 2 identifies
a chat answer saved as a note. The current archive has 13 user notes and 166
saved-answer notes with preserved Markdown. Another 184 legacy Markdown files
are not notes: 183 contain only a mind-map UUID reference and one has no useful
body, produced because the old materializer did not filter those RPC shapes.
They remain physically preserved but are explicitly operational evidence, not
Assets or historical content. Six generated briefs from the immutable
historical archive are assistant note-assets as well. The same preservation
rule recovers every mind-map JSON;
29 maps previously misclassified as type-4 quiz/flashcard rows are correctly
disambiguated by their saved map representation.

### Key decision

`guide.summary` becomes a system message (sequence=0) in notebooks that
have a guide — guarantees `message_count >= 1`. ~15% of notebooks have no
guide (empty/Untitled/recently-created) — no system msg, but
branch/conversation still exist.

## Source-level summary + tags + questions

RPC `tr032e` discovered via probe. Each guide has ~800-1000 chars summary
+ 5 tags + 3 questions generated by the model. Coverage: ~1174/1173 sources
with summary (1 source duplicated across notebooks).

## Descriptive Quarto (3 documents)

- `notebooks/notebooklm.qmd` (consolidated, stacked bars per-account).
- `notebooks/notebooklm-acc-1.qmd` (account-1 only).
- `notebooks/notebooklm-acc-2.qmd` (account-2 only).
- Google orange `#F4B400`. Render < 30s each.

## Validated CRUD scenarios (via mobile app)

| Scenario | Result |
|---|---|
| Rename | title matches in parquet |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preserved, title preserved |
| Add source | sources.parquet increments |
| Pin | NotebookLM **has no pin feature** upstream — see [known limitations](../../../known-limitations.md#notebooklm) |

### Empirical finding

Listing `update_time` is **volatile** — server periodically reindexes +
accessing the notebook bumps it. Reconciler uses semantic hash (not
timestamp) to decide refetch — behavior already mitigated by design.

## Asset downloads — Range-chunked (mandatory, 2026-05-12)

**Bug histórico** (custou horas em multiplas sessões): downloads de audios
(.m4a) via `lh3.googleusercontent.com/notebooklm/{token}` davam timeout de
5min, faziam o sync parecer travado / consumir RAM até congelar a maquina.

**Causa raiz** (validada empiricamente via Playwright `context.request`):
o backend desse host **trava a conexão se você pedir o arquivo inteiro
de uma vez**, mas responde 206 Partial Content rápido pra Range pequeno.

| Pedido | Resultado |
|---|---|
| `GET` sem header | TIMEOUT |
| `GET Range: bytes=0-` | TIMEOUT |
| `GET Range: bytes=0-{length-1}` (= full size) | TIMEOUT |
| `GET Range: bytes=0-10MB` | 206 OK 2.6s |
| `GET Range: bytes=0-5MB` | 206 OK 1.8s |
| `GET Range: bytes=0-1MB` | 206 OK 1.4s |
| `HEAD` | 200 OK 1-2s com content-length |

**Fix em `src/platforms/notebooklm/extractor/api_client.py::download_asset`:** HEAD
pra content-length, GET em chunks de 8MB com `Range: bytes={start}-{end}`
explícito, concat dos bytes. Cada chunk responde 206; `resp.ok` cobre
200/206. Audio de 16MB que travava → 7.2s.

**Não tente "otimizar" de volta pra GET único** — o servidor rejeita.
Comentário em `api_client.py` documenta os testes empíricos pra preservar
a memória institucional do conserto.

**Logging em `asset_downloader.py`:** progresso a cada 200 alvos + top 5
erros + `flush=True` em todos os prints (essencial pra streaming do
dashboard).

### Linha do tempo real dos audios (acc-1, pra calibrar expectativa)

| Data/hora | Audios baixados | Contexto |
|---|---|---|
| 2026-05-02 | 5 | primeiro sync — so 5 cabiam antes do timeout travar |
| 2026-05-12 02:27-03:02 | 78 | rajada da sessao de debug do fix (travou em 03:02) |
| 2026-05-12 03:12 | 13 | sessao seguinte completou os faltantes |
| **total pos-fix** | **96 / 97** | de 97 no catalogo (1 audio sem URL targetavel) |

acc-2: 11 pre-fix → 29 pos-fix (de 30 no catalogo; 1 com HTTP error
real — URL morta upstream).

**Pegadinha de leitura de log:** o counter `audios dl=N skip=M` mostra
**apenas a rodada atual**. `skip=83` na sessao das 03:12 nao significava
"83 audios historicos" — eram 5 originais + 78 da rajada da madrugada.
Pra historico real, sempre `find ... -name "*.m4a" -mtime -1` + `stat`
nos arquivos fisicos.

### Custo dos proximos syncs (incremental por design)

`skip_existing=True` no `asset_downloader.py` — audios ja baixados
(arquivo existe + size > 0) sao **skip**. Discovery + reconcile rodam
sempre; downloads sao incrementais.

| Cenario | Custo (acc-1, 94 notebooks) |
|---|---|
| Nada novo (re-run) | ~30-60s total (discovery + reconcile + 1827 skips) |
| 1 audio novo | ~5s extra (1 chunk de 8MB / connection) |
| 10 audios novos | ~30s extra (8 paralelos, 3-5s cada) |
| 100 audios novos | ~5min extra |

**Audios novos em notebooks ja conhecidos** sao detectados normalmente —
discovery refaz os 94 notebooks, parseia `gArtLc` (artifacts), e qualquer
type=1 (audio) novo com URL vira target. **Nao requer captura "do zero"**
nem invalidacao manual.

## Historical corporate archive (inaccessible account)

This archive is separate from the three active account profiles. It contains
11 notebooks / 33 messages / 228 source metadata rows / 27 outputs / 6 briefs
and 33 guide questions from an old extractor capture.

- Immutable input: `data/external/notebooklm-snapshots/<archive>-YYYY-MM-DD/`
- Format adapter: `src/platforms/notebooklm/historical_parser.py`
- Official entry point: `python -m src.platforms.notebooklm.commands.parse`
- Provenance: `capture_method='historical_notebooklm_snapshot'`
- Account identity: stable `archive:<snapshot-directory>` key, which cannot be
  confused with active `account-1`, `account-2`, or `account-3` profiles.
- Output: the same nine `notebooklm_*.parquet` files as current accounts; no
  parallel `_manual_` Parquet family.

Every fallback ID is deterministic. Because filesystem mtimes change after a
DVC restore, inferred timestamps use the `YYYY-MM-DD` capture date encoded in
the snapshot directory name; real timestamps present in chat turns are kept.
The 228 source rows contain preserved metadata but empty body content because
the old capture did not retain source text.

The parse command validates the configured historical root and every notebook
before writing. If the DVC snapshot is absent, empty, or malformed, it exits
without shrinking `processed/`. The operator can request a deliberately
current-only rebuild with `--without-historical`.

This is also the account-retirement pattern for future sources: a current
account that becomes inaccessible remains in its cumulative `raw/merged`
tree and must no longer be synced; an older incompatible capture belongs in
`data/external/` with a platform-owned adapter. Data never captured before
access loss cannot be recovered afterward.

## Operational observation — 2026-08-30

An incremental run for **account-1** completed capture, assets, and
reconciliation. Capture reported 129 discovered notebooks, 128 composite
fetches, and zero notebook RPC errors. Asset processing completed with 1,826
page images downloaded, 2,217 existing page images skipped, and no recorded
asset errors. Reconciliation reported 32 added, 96 updated, 1 copied, and 1
preserved-missing notebook. The parser was not run in that collection session.

These fetches must **not** be interpreted as 128 newly created notebooks:
they are the result of the lite-fetch classifier deciding that the current
metadata, notes, or artifact response differed from the previous raw body.
At the time of observation, the cumulative raw directory contained 256 JSON
files while current `discovery_ids.json` contained 129 entries. Structural
inspection showed 130 files in the current schema (129 in discovery plus 1
preserved record) and 126 legacy-schema records (`notebook_uuid`,
`mind_map_uuid`, `raw`). Do not clean either population to make counts match.

Before a rerun, compare the three lite-fetch inputs (`rLM1Ne`, `cFji9`, and
`gArtLc`) for a small sampled set against the prior raw body, with special
attention to volatile/presigned values. Confirm the account identity through a
non-secret local profile-preferences mapping: account-1 is
`hello.marlonlemes@gmail.com`; account-2 is `marloonlemes@gmail.com`.

### Diagnostic outcome — 2026-08-30

A controlled incremental validation on account-2 (no UI interaction between
runs) identified volatile source fields inside the lite `rLM1Ne` metadata:
one regenerated URL and two derived text fields per source. The classifier now
masks only those fields, while retaining source identity and all full-body
reconciliation checks. The validated no-op run discovered 53 notebooks and
classified all as copies (`0 fetch`); reconciliation reported `added=0`,
`updated=0`, `copied=53`, and `preserved_missing=2`.

The same run found five binary assets whose upstream URLs returned HTTP errors.
They were recorded in `assets_log.json`; no existing asset or historical raw
record was removed or overwritten. A validation on account-1 then captured 30
note differences and reconciled them as updates; its immediate repeat without
UI interaction classified all 129 notebooks as copies and reconciled
`updated=0`, confirming those differences did not recur as an unstable
lite-fetch signal. The account-1 asset pass recorded 64 upstream HTTP errors,
also without removal or overwrite. The NotebookLM parser then completed with
185 conversations, 156 messages, 1,706 sources, 174 notes, 648 outputs, and
468 guide questions across the two live accounts.

## Operational validation — 2026-09-20

The three-account headless pipeline completed capture, reconciliation, parse,
unify, and all 9 selected Quarto renders without publication. The first pass
found one new notebook in account-3 and produced 200 conversations, 193
messages, 1,973 sources, 609 outputs, 513 guide questions, and 1,745 source
guides across the three active accounts plus the historical archive.

The run exposed two incremental asset defects. Current audio URLs can carry a
comma-bearing media transform suffix such as `=mm,140`; the regex fallback
truncated that suffix and caused HTTP 400. Audio extraction now prefers the
mapped `gArtLc` position and retains the complete URL. The resulting successful
download also exercised recovery from an earlier `reference_only` delivery:
the vault projection now uses the immutable digest and size from a later
available observation, without rewriting the original delivery record.

The repair recovered the new account-3 audio and one account-1 audio. A clean
repeat classified all 186 currently discovered notebooks as unchanged
(`129 + 53 + 4` copies), reconciled with zero warnings, and retained historical
upstream failures without deleting evidence: 63 in account-1, 5 in account-2,
and 2 in account-3. The final parser materialized 10,445 NotebookLM assets and
5,252 asset links; unified data contains 19,674 assets. Vault verification
covered all 21 scopes and 11,748 physical blobs, and the complete repository
suite passed. This validation was intentionally run with no DVC or Git
publication.

## Related documents

- `incident-lite-fetch-regression-2026-08-30.md` — diagnosis, narrow fix, validation,
  and future-change protocol for the lite-fetch regression.
- `docs/extractor-engineering/platforms/web/notebooklm/server-behavior.md` — upstream behavior.

## Commands

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.sync             # all active accounts
PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.sync --account 1 # only account 1
PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.sync --account 3 # only account 3
PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.parse
PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.parse --without-historical  # explicit current-only rebuild
for f in notebooklm notebooklm-acc-1 notebooklm-acc-2; do
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/${f}.qmd
done
```
## Asset vault transition

`vault` is the default asset reader, using `data/assets` and `data` unless roots
are overridden explicitly. `legacy` remains an explicit temporary rollback;
filesystem contents never select the mode. The legacy tree remains preserved,
while the vault reader projects the same public `Asset`, `AssetLink`, and
`Message.asset_paths` contract. NotebookLM is library-scoped: preserved files
retain their evidenced source, note, or output-object links, including
multi-file outputs, without treating text-only domain records as assets. See
the [operational transition](../../../../operations/pipeline.md#transicao-do-asset-vault).

## Explicit login-health check

A single `wXbhsf` notebook listing is the established read-only check; a successful parsed response is the only path to `valid`. Profile presence alone never produces a valid status. The check is
read-only, runs only after an explicit operator action, and never refreshes tokens.
