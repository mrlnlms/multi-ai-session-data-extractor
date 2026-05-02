# NotebookLM — comportamento do servidor (validado empiricamente)

Bateria CRUD UI executada via app mobile + browser em 2026-05-02. Resultados
documentados aqui (regra dura do projeto: shipped só com CRUD validado).

## Bateria CRUD validada (2026-05-02)

| Operação | Validação | Status |
|---|---|---|
| Rename | "Heatmap Studies" → "Heatmap estudos" (`b1b8da1f`) — title bate em parquet | ✅ |
| Delete | "Westward Mushrooms" (`0be7e3ec`) — `is_preserved_missing=True`, `last_seen_in_server=2026-05-02`, title preservado | ✅ |
| Pin/Star | **Feature não exposta no NotebookLM** (confirmado no app mobile) | ✅ N/A |
| Add source | 1 PDF novo capturado em notebook existente — sources acc-1 = 974 → 975 | ✅ |

## Comportamento do servidor descoberto

### `update_time` é VOLÁTIL — não é proxy de "user mexeu"

Validação empírica: 93/94 notebooks tiveram `update_time` bumped entre
2 syncs consecutivos, mesmo sem o user ter modificado eles.

**Causa:** servidor reindexa periodicamente (provavelmente "last indexed",
não "last modified"). Acessar um notebook na UI também bumpa o timestamp.

**Implicação:** `update_time` do `wXbhsf` listing **não pode** ser usado
como proxy pra "user fez algo". Já documentado no orchestrator.

**Mitigação (já implementada):**
- Reconciler usa **hash semântico do conteúdo** (excluindo timestamps)
  via `_eq_lenient` pra decidir to_use vs to_copy
- Lite-fetch compara 3 RPCs leves (rLM1Ne + cFji9 + gArtLc) pra
  classificar mudança real

### Delete: preservation funciona

Notebook deletado no servidor:
- Sai do `discovery_ids.json` atual
- Reconciler marca `_preserved_missing=True` no merged
- Title + last_seen_in_server preservados
- Não é re-baixado nas próximas runs (skip natural)

### Acesso ao notebook bumpa update_time

Confirmado pelo user: "ele sempre sobe só por acessar". Acessar (mesmo
sem editar) move o notebook pro topo da lista — provavelmente o servidor
trata acesso como "interação".

Sem impacto pro extractor (mitigado por hash semântico).

### Pin/Star: não existe no NotebookLM

Confirmado no app mobile pelo user. NotebookLM tem UI minimalista — sem
favorites/pinned. Único "ranking" visual é por update_time decrescente.

`is_pinned` no schema canônico fica `None` pra todos os notebooks NotebookLM.
Esperado e correto.

## Conclusão

Cenários CRUD aplicáveis ao NotebookLM **todos validados**. Único caso
"N/A" é pin (feature inexistente). Comportamento volátil de update_time
já estava mitigado no design do reconciler.

**Status:** ✅ pronto pra shipped.
