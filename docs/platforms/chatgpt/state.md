# ChatGPT — cobertura técnica

## Pipeline

- **Pasta única cumulativa:** `data/raw/ChatGPT/` e `data/merged/ChatGPT/`.
- **Sync orquestrador (4 etapas):** `scripts/chatgpt-sync.py` — capture +
  assets + project_sources + reconcile.
- **Captura:** **headed** (Cloudflare detecta headless). Inclui DOM scrape
  de projects + voice pass + auth via cookies.
- **Auth:** profile persistente em `.storage/chatgpt-profile-<conta>/`
  (gerado via `scripts/chatgpt-login.py`).
- **Fail-fast contra discovery flakey** — `_get_max_known_discovery` rglob
  recursivo, threshold 20% (aborta antes do save se discovery atual <80%
  do maior histórico).

## Cenários CRUD validados

| Cenário | Resultado |
|---|---|
| Conv deletada | `is_preserved_missing=True` no merged |
| Conv atualizada (msg nova) | `updated`, `update_time` bumpado |
| Conv nova | `added` |
| Conv renomeada | `updated` (servidor bumpa `update_time`; guardrail extra cobre edge case de não-bump) |
| Project criado | discovery sobe, novo `g-p-*` em `project_sources/` |
| Project deletado inteiro | sources marcadas `_preserved_missing`, binários físicos intocados, chats internos preservados |

## Volume de referência

- 1171 conversations cumulativas (1168 active + 3 preserved_missing).
- `LAST_RECONCILE.md` e `reconcile_log.jsonl` atualizados a cada run.

## Parser canônico

`src/parsers/chatgpt.py` (`ChatGPTParser`, `source_name="chatgpt"`).
Output em `data/processed/ChatGPT/`: conversations.parquet,
messages.parquet, tool_events.parquet, branches.parquet.

### Cobertura

- **Tree-walk completo** — preserva branches off-path.
- **Voice** com `direction in/out`.
- **DALL-E** mapeado em ToolEvent.
- **Uploads do user** (Message com `image_asset_pointer`).
- **Tether quote**, **canvas**, **deep_research**.
- **Custom GPT vs project** distinguidos.
- **Preservation** via `is_preserved_missing` + `last_seen_in_server`.

### Volume típico

1171 convs / 17.583 msgs / 3109 tool_events / 1369 branches. Idempotente
byte-a-byte.

## Quarto descritivo

- `notebooks/chatgpt.qmd` — data-profile "zero trato": schema + cobertura
  + amostras + distribuições + preservation. Sem sentiment/clustering/topic.
- Stack: DuckDB + Plotly + itables.
- Output: `notebooks/_output/chatgpt.html` (~52MB self-contained).
- Render: ~20s pra ~1k convs.

## Comandos

```bash
PYTHONPATH=. .venv/bin/python scripts/chatgpt-sync.py --no-voice-pass
PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
```

Sem `QUARTO_PYTHON`, Quarto tenta python do system e falha por falta de
deps (duckdb, plotly, itables).

## Documentos relacionados

- `docs/platforms/chatgpt/server-behavior.md` — comportamento upstream.
