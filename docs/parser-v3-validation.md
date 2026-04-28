# Parser v3 — validação cruzada com v2

Comparação empírica entre `chatgpt_v2` (legacy MVP) e `chatgpt_v3` (parser
canônico) sobre o mesmo `data/merged/ChatGPT/chatgpt_merged.json` (1171 convs,
2026-04-28).

Resultado: **v3 cobre tudo que v2 cobre + branches off-path + ToolEvents**.
Sem regressões. Divergências documentadas abaixo.

---

## Conversations

| | v2 | v3 |
|---|---|---|
| count | 1171 | 1171 |
| ids equal | ✅ | ✅ |
| campos novos preenchidos | — | project_id (1045), gizmo_id Custom GPT (1), is_preserved_missing (3), last_seen_in_server (1171) |

Sem regressão. v3 enriquece com 6 campos novos (preservation + gizmo distinction).

---

## Messages

| Métrica | v2 | v3 |
|---|---|---|
| Total messages | 17312 | 17583 |
| Off-path (branches forks) | 0 | ~271 |
| Marcadas `is_hidden` | — (filtradas) | 1429 |
| Visíveis em branch ativa | — | 14005 |

### Por que v3 (visível) < v2

v3 é mais rigoroso na detecção de hidden:
- v2: filtra apenas `metadata.is_visually_hidden_from_conversation`
- v3: filtra também `weight==0` e `recipient != "all"` (chamadas internas do assistant pra tools)

Distribuição em v3:
- `internal_recipient`: 1403 (assistant → tool calls)
- `visually_hidden`: 26

Decisão: v3 **preserva** essas mensagens com `is_hidden=True` ao invés de descartar. Downstream filtra conforme caso de uso. Schema fica mais fiel ao raw.

### Por que v3 (total) > v2

271 msgs adicionais em branches off-path: caminhos alternativos do mapping que v2 ignora ao caminhar `current_node → root`. v3 percorre o mapping inteiro.

---

## Tool Events

| | v2 | v3 |
|---|---|---|
| count | 0 (não gera) | 3109 |

v2 ignora msgs com `role=tool` e `content_type=tether_quote`. v3 estrutura como `ToolEvent`:

| event_type | count |
|---|---|
| quote (tether_quote) | 538 |
| search (browser, web) | 537 |
| code (python) | 510 |
| canvas (canmore.*) | 411 |
| file_search | 327 |
| deep_research | 309 |
| other (JIT plugins) | 277 |
| memory (bio) | 144 |
| image_generation (DALL-E) | 50 |
| computer_use | 12 |

Counts maiores que Fase 2a (3030) por inclusão de events em branches off-path.

---

## Branches

| | v2 | v3 |
|---|---|---|
| count | 0 (não gera) | 1369 |
| convs com ≥2 branches (fork) | — | 77 |
| max branches em uma conv | — | 9 |

Plan §1.2: "v2 só pegava branch ativa (path pro current_node) — v3 pega todas."

`is_active=True` em exatamente 1 branch por conv (a que contém `current_node`).

---

## Idempotência

```
md5 hash run #1 == md5 hash run #2
```

Confirmado byte-a-byte em todos os 4 parquets.

---

## Achados que ajustaram a implementação vs plan formal

Durante implementação, dados empíricos contradisseram premissas do plan §4.3:

1. **DALL-E sempre em `role=tool`** (46/46 no merged), nunca em assistant.
   - Plan §4.3 assumiu Message com asset_paths. Corrigi: ToolEvent com
     `event_type='image_generation'` + `file_path` resolvido.
2. **User uploads (`image_asset_pointer` sem `metadata.dalle`) em `role=user`**
   (402 msgs). Não previsto explicitamente no plan; implementei separado:
   `Message.asset_paths` populado, marker `image_upload` em `content_types`.
3. **Fixture sanitizou `dalle.text2im` → `t2uay3k.sj1i4kz`**. Adicionei
   detecção semântica (presença de `image_asset_pointer` + `metadata.dalle`)
   sobrepondo classifier por nome.
4. **`finish_reason` tem valores além dos findings**: `stop` (8086),
   `max_tokens` (169), `unknown` (124), `interrupted` (55).

---

## Critérios de pronto Fase 2c (plan §6)

- ✅ Diff documentado (este doc)
- ✅ Sem regressões: convs idênticas, msgs do v3 cobrem msgs do v2 com
  classificação mais rica (hidden), tool events só no v3 são complemento
- ⏳ **Aprovação humana antes de promover v3 a `chatgpt`** (Fase 2d)

---

## Comando pra reproduzir

A validação acima foi feita em 2026-04-28 antes da promoção do v3 a `chatgpt`.
O `chatgpt_v2.py` original ficou em `_backup-temp/parser-v3-promocao-2026-04-28/`
caso seja necessário re-rodar o diff.

Pós-promoção, o parser canônico está em `src/parsers/chatgpt.py`:

```bash
PYTHONPATH=. .venv/bin/python -c "
from pathlib import Path
from src.parsers.chatgpt import ChatGPTParser

p = ChatGPTParser()
p.parse(Path('data/merged/ChatGPT/chatgpt_merged.json'))
print(f'{len(p.conversations)} convs, {len(p.messages)} msgs, {len(p.events)} events, {len(p.branches)} branches')
"
```
