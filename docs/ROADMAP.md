# Roadmap

Open work items. Closed via shipped releases are removed from this list
(see `git log` for history). For broader context, see
[README.md](../README.md) and [CLAUDE.md](../CLAUDE.md).

## Future platforms

(none right now — Grok and Kimi shipped 2026-05-09.)

## Operational

### Generalizar discovery-drop fallback (7 plats restantes)

ChatGPT é a única plat com fallback automático contra discovery parcial
(`refetch_known_via_page` via `/conversations/batch`). As 7 demais
(Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity, Grok, Kimi)
ainda têm `RuntimeError` no orchestrator quando drop > 20% detectado.

**Pra cada plat falta:**

1. `src/extractors/<plat>/refetch_known.py` — refetch full state via endpoint
   API próprio (batch quando disponível; um-por-um caso contrário). Cada
   plat tem signature distinta — não dá pra extrair helper genérico de
   alto nível, só utilities pequenas (threshold, leitura de raw).
2. Hook no orchestrator: substituir `raise RuntimeError(...)` por
   `await refetch_known_via_<plat>(...)` quando drop > threshold.
3. Tests unitários com mocks (validação empírica só possível quando o
   sintoma rolar de verdade).

**Tamanho real:** ChatGPT levou 5 commits + ~36h de trabalho concentrado
(`e759760`..`d1e490c`). Pras 7 restantes, esperado 5-10 dias úteis
distribuídos. Claude.ai está mais perto — já tem
`scripts/claude-refetch-known.py`, mas resolve outro problema (gap-fill
pós-fetch, não discovery parcial). Reaproveita ~30% do código.

**Mitigation manual atual** quando rolar `RuntimeError`:
- Claude.ai: `scripts/claude-refetch-known.py` ou `claude-sync.py --full`
- Outras: `<plat>-sync.py --full` (ignora fail-fast, refaz tudo)

### ChatGPT capture-delete cycle

The reconciler infrastructure (with `preserved_missing` flag for items
removed from the server) is in place and validated. Operational next
step: gradually delete old conversations on the server. The next
incremental capture (`--since last`) should surface deleted IDs as
`preserved_missing` while keeping the local raw intact. Replicable to
other platforms once their reconcilers are equally validated.

This is mostly a manual operational task — kept here as a reference
point when reviewing chat details and deciding what to remove from the
server. Automation is feasible (script that lists conversations older
than N days without recent updates and calls the delete endpoint) but
risky: a bug in the selection logic deletes the wrong conversations
server-side, and although the reconciler preserves the local copy, you
lose the ability to re-fetch updated versions from the server. Start
manual; consider automation only after confidence is high.
