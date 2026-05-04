# NotebookLM — cobertura técnica

NotebookLM não é chat puro: cada notebook é um workspace que gera até 9
tipos de outputs (audio, blog, video, flashcards, quiz, data table, slide
deck PDF+PPTX, infographic, mind map).

## Pipeline

- **Multi-conta** — até 3 contas (acc-1, acc-2, acc-3 legacy). Profiles
  em `.storage/notebooklm-profile-{1,2}/` (gerados via
  `scripts/notebooklm-login.py`).
- **Pasta única cumulativa per-account:** `data/raw/NotebookLM/account-{N}/`
  e `data/merged/NotebookLM/account-{N}/`.
- **Sync orquestrador (3 etapas multi-conta):**
  `scripts/notebooklm-sync.py` — capture per-account + assets + reconcile
  per-account.
- **Captura headless.**

### Volume de referência (corpus de exemplo)

- acc-1: 95 notebooks / 974 sources / 1484 assets (4 audios + 12 videos +
  30 slide decks + 1344 page images + 54 text artifacts + 76 notes + 45
  mind_maps).
- acc-2: 48 notebooks / 199 sources / 38 assets + 96 notes + 53 mind_maps.

## RPCs mapeados (api_client + fetcher)

- `wXbhsf` — list notebooks.
- `rLM1Ne` — metadata.
- `VfAZjd` — notebook guide.
- `khqZz` — chat (None na maioria).
- `cFji9` — notes.
- `gArtLc` — artifacts (9 tipos).
- `v9rmvd` — artifact content individual (types 2/4/7/9).
- `CYK0Xb` — mind_map tree (payload `[nb_uuid, mm_uuid]`).
- `hPTbtc` — mind_map UUID.
- `hizoJc` — source content.
- `tr032e` — source guide (descoberto via probe Chrome MCP + Playwright
  headed; payload `[[[[source_uuid]]]]`).

## Reconciler v3 (FEATURES_VERSION=2)

Preservation completa per-account, pasta única cumulativa (sem subpastas
dated), `LAST_RECONCILE.md` + `reconcile_log.jsonl` per-account.

## Parser canônico

`src/parsers/notebooklm.py` + `_notebooklm_helpers.py`. Rewrite total.
**9 parquets** (4 canônicos + 5 auxiliares):

- **Canônicos:** conversations / messages / tool_events / branches.
- **Auxiliares:** sources / source_guides / notes (kind ∈ {note, brief}) /
  outputs (cobre 8 dos 9 tipos + `mind_map=10`) / guide_questions.

### Decisão chave

`guide.summary` vira system message (sequence=0) em notebooks que têm
guide — garante `message_count >= 1`. ~15% dos notebooks não tem guide
(vazios/Untitled/recém-criados) — sem system msg, mas branch/conversation
continuam.

## Source-level summary + tags + questions

RPC `tr032e` descoberto via probe. Cada guide tem ~800-1000 chars summary
+ 5 tags + 3 questions geradas pelo modelo. Cobertura: ~1174/1173 sources
com summary (1 source duplicado entre notebooks).

## Quarto descritivo (3 documentos)

- `notebooks/notebooklm.qmd` (consolidado, stacked bars per-account).
- `notebooks/notebooklm-acc-1.qmd` (account-1 only).
- `notebooks/notebooklm-acc-2.qmd` (account-2 only).
- Cor laranja Google `#F4B400`. Render < 30s cada.

## Cenários CRUD validados (via app mobile)

| Cenário | Resultado |
|---|---|
| Rename | title bate em parquet |
| Delete | `is_preserved_missing=True`, `last_seen_in_server` preservado, title preservado |
| Add source | sources.parquet incrementa |
| Pin | NotebookLM **não tem feature de pin** upstream — ver [LIMITATIONS.md](../../LIMITATIONS.md#notebooklm) |

### Achado empírico

`update_time` do listing é **volátil** — servidor reindexa periodicamente
+ acesso ao notebook bumpa. Reconciler usa hash semântico (não timestamp)
pra decidir refetch — comportamento já mitigado por design.

## Account-3 legacy (snapshot extinto)

11 notebooks / 33 msgs / 27 outputs / 6 briefs via parser legacy
`src/parsers/manual/notebooklm_legacy_more_design.py`,
`capture_method='legacy_notebooklm_<source>'`. Snapshot raw em
`data/external/notebooklm-snapshots/<source>/`. Quarto:
`notebooks/notebooklm-legacy.qmd`.

## Documentos relacionados

- `docs/platforms/notebooklm/server-behavior.md` — comportamento upstream.

## Comandos

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py             # ambas contas
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py --account 1 # só conta 1
PYTHONPATH=. .venv/bin/python scripts/notebooklm-parse.py
for f in notebooklm notebooklm-acc-1 notebooklm-acc-2; do
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/${f}.qmd
done
```
