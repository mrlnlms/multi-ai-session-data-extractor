# NotebookLM — comportamento do servidor (validado empiricamente)

A bateria CRUD UI é executada pelo user manualmente após o full sync.
Resultados documentados aqui (regra dura do projeto: shipped só com
CRUD validado).

## Bateria pendente (requer interação user)

### Rename
- [ ] Renomear 1 notebook na UI da conta 1
- [ ] Validar: title bate em parquet apos sync? `update_time` bumpa?

### Delete
- [ ] Deletar 1 notebook na UI (escolher antigo, sem importância)
- [ ] Validar: `is_preserved_missing=True`? `last_seen_in_server` preservado?
  Title preservado no merged?

### Pin/Star (descobrir feature)
- [ ] Explorar UI atrás de "pin", "star", "favorite", "fixar"
- [ ] Se existir: pinar 1 notebook + sync + validar `is_pinned=True`
- [ ] Se não existir: documentar como "feature não exposta no NotebookLM"

### Add source
- [ ] Adicionar 1 PDF/link novo em 1 notebook existente
- [ ] Validar: source aparece em `notebooklm_sources.parquet`?
  `update_time` do notebook bumpa? Conteúdo extraido populado?

### Remove source
- [ ] Remover 1 source de 1 notebook
- [ ] Validar: source vira preserved_missing? Texto preservado mesmo após
  remoção? (provavel: comportamento similar a ChatGPT project_sources)

### Generate output novo
- [ ] Gerar 1 audio overview / blog / data table novo em 1 notebook
- [ ] Validar: aparece em `notebooklm_outputs.parquet` na próxima sync?
  Asset_path populado pra binários?

### Delete output
- [ ] Deletar 1 output gerado
- [ ] Validar: comportamento (preserved? sumido? skip?)

## Comportamento esperado (hipóteses)

Baseado em padrões das 6 plataformas anteriores:

| Operação | Hipótese |
|---|---|
| Rename notebook | `update_time` bumpa (igual ChatGPT/Gemini/Claude.ai/etc) |
| Delete notebook | `is_preserved_missing=True`, `last_seen_in_server` preservado |
| Pin notebook | NotebookLM **provavelmente não tem feature de pin** (UI minimalista) |
| Add source | `update_time` bumpa, source novo capturado |
| Remove source | source vira `_preserved_missing`, texto preservado |
| Generate output | output novo capturado na próxima sync |

Atualizar este doc com resultados reais após bateria.

## Conclusão

(Preencher após bateria.)

---

**Status:** ⏳ Aguardando bateria CRUD UI manual.
