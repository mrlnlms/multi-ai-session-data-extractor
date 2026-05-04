# Gemini — cobertura técnica

## Pipeline

- **Multi-conta** — 2 contas Google. Profiles em
  `.storage/gemini-profile-{1,2}/` (gerados via `scripts/gemini-login.py`).
- **Pasta única cumulativa per-account:** `data/raw/Gemini/account-{N}/` e
  `data/merged/Gemini/account-{N}/`.
- **Sync orquestrador (3 etapas multi-conta):**
  `scripts/gemini-sync.py` — capture per-account + assets + reconcile
  per-account. Itera ambas contas em sequência (default) ou
  `--account N` pra rodar só uma.
- **Captura headless** (sem Cloudflare em runtime).

## Cobertura

Conversations + assistant messages + tool events + imagens
(lh3.googleusercontent.com) + Deep Research markdown reports extraídos.

### Volume de referência

- 47 + 33 = 80 convs / 560 msgs / 889 tool_events.
- 215 imagens baixadas + 18 Deep Research markdown reports.
- 8 modelos detectados (2.5 Flash, 3 Pro, Nano Banana, 3 Flash Thinking,
  etc).

## Parser canônico

`src/parsers/gemini.py` + `_gemini_helpers.py`.

Schema raw é **posicional** (Google batchexecute, sem keys) — caminhos
descobertos via probe (`scripts/gemini-probe-schema.py`):

- `turn[2][0][0]` → user text.
- `turn[3][0][0][1]` → assistant text (chunks).
- `turn[3][21]` → model name.
- `turn[3][0][0][37+]` → thinking blocks (heurística >=200 chars excl.
  main response).
- `turn[4][0]` → timestamp epoch secs.

### Cobertura

- ~41% das assistant msgs com thinking.
- **Image generation** via regex sobre JSON do turn → ToolEvent +
  `Message.asset_paths` resolvidos via `assets_manifest.json` per-account.
- **Multi-conta com namespace `account-{N}_{uuid}`** em
  `conversation_id`.
- **Search/grounding citations** (Search + Deep Research) — 1 ToolEvent
  `search_result` por citation, dedup por URL; também populam
  `Message.citations_json`.

## Cenários CRUD validados

| Cenário | Resultado |
|---|---|
| Rename | title bate em parquet |
| Pin | `is_pinned=True` (descoberto via probe — campo `c[2]` do listing MaZiqc retorna `True` quando pinado, `None` senão) |
| Delete | `is_preserved_missing=True`, title + `last_seen` preservados |
| Share URL | upstream-only — ver [LIMITATIONS.md](../../LIMITATIONS.md#gemini) |

## Quarto descritivo (3 documentos)

- `notebooks/gemini-acc-1.qmd` (template canônico, account-1 only).
- `notebooks/gemini-acc-2.qmd` (template canônico, account-2 only).
- `notebooks/gemini.qmd` (consolidado, com stacked bars por conta nas
  seções-chave).
- Cor: azul Google `#4285F4` (acc-1), azul mais escuro `#1A73E8` (acc-2).

## Documentos relacionados

- `docs/platforms/gemini/server-behavior.md` — comportamento upstream.
- Probes: `scripts/gemini-probe-schema.py`,
  `scripts/gemini-probe-pin-share.py`.

## Comandos

```bash
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py             # ambas contas
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py --account 1 # só conta 1
PYTHONPATH=. .venv/bin/python scripts/gemini-parse.py
for f in gemini gemini-acc-1 gemini-acc-2; do
  QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/${f}.qmd
done
```
