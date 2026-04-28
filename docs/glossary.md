# Glossário — termos do projeto

Pra entender logs, status e mensagens dos scripts.

---

## Os 3 números que parecem iguais mas NÃO são

### 1. Discovery (foto do servidor agora)

**O que é:** quantas conversas o ChatGPT.com está mostrando **neste momento**.

**Pode subir?** Sim, quando você cria conv nova.
**Pode baixar?** Sim, quando você deleta conv ou ela expira no servidor.
**É dado nosso?** Não — é foto do estado do servidor, refletida pela API.

Onde aparece: log `Discovery: {'total': 1168}` durante captura.

---

### 2. Merged (nosso histórico cumulativo)

**O que é:** o catálogo local com TODAS as convs que já vimos alguma vez.

**Pode subir?** Sim, quando capturamos algo novo.
**Pode baixar?** **Não.** Convs apagadas no servidor viram `preserved_missing` mas continuam aqui.
**É dado nosso?** Sim — é a fonte de verdade local.

Onde fica: `data/merged/ChatGPT/chatgpt_merged.json`.

---

### 3. Baseline (régua interna do fail-fast)

**O que é:** o **maior valor de discovery** já registrado em qualquer log de captura no disco.

**Serve pra que?** Detectar quando o servidor da OpenAI tá flakey e mente. Se a discovery atual cai mais de 20% vs baseline, o sistema **aborta antes de salvar dado corrompido**.

**É dado nosso?** Não — é instrumento de medição. Pode ser resetado sem perder dado.

Função: `_get_max_known_discovery()` em `src/extractors/chatgpt/orchestrator.py`.

---

## Outros termos que aparecem nos logs

### Preserved missing

Conv (ou source) que **estava no nosso merged anterior mas sumiu do servidor**. Não apagamos — marcamos com `preserved_missing: true` (no caso de conv) ou `_preserved_missing: true` (no caso de source).

Princípio: **nunca rebaixar histórico mesmo quando o servidor esquece.**

### Fail-fast

Aborta a captura **antes de salvar** quando detecta sintoma de bug do servidor (discovery muito menor que o histórico). Threshold: 20% de queda.

Razão: sem isso, raw fica corrompido e contamina a próxima base incremental.

### Hardlink

Mesmo arquivo físico no disco, com **mais de um nome** (mais de um path). Não duplica espaço — só etiquetas extras apontando pro mesmo livro.

Usado quando capturas antigas e novas referenciam os mesmos binários (assets, project_sources). Apagar um path = arrancar uma etiqueta. O arquivo só some quando a última etiqueta for arrancada.

### Raw

A pasta `data/raw/ChatGPT/` — captura direta do servidor, sem reconciliação. Mutada in-place a cada run. Tem `chatgpt_raw.json` + binários (assets, project_sources) + logs.

### Reconcile

O processo que pega o **raw atual** + **merged anterior** e produz o **merged novo** com toda a preservation aplicada (convs apagadas viram preserved, novas viram added, atualizadas viram updated, inalteradas viram copied).

### Incremental

Modo de captura que NÃO refetcha tudo. Só baixa convs que mudaram desde a última run (comparando `update_time`). Acelera muito as runs depois da primeira.

### Brute force (`--full`)

Modo de captura que **refetcha tudo**. Usa quando tem suspeita de raw corrompido ou quer reset.

### Voice pass

Etapa opcional que escaneia convs procurando mensagens de áudio (Voice Mode) cujo texto não veio pela API. Pra cada candidata, abre a conv no DOM e raspa o transcript. Lento — pode-se pular com `--no-voice-pass`.

---

## Os 4 estados de uma conv no reconcile

| Estado | Significado | Onde está |
|---|---|---|
| `added` | Existe no current, não existia no previous | conv **nova** |
| `updated` | Existe em ambos, mas current tem `update_time` ou enrichment maior | conv **mudou** |
| `copied` | Existe em ambos, sem mudança | conv **inalterada** |
| `preserved_missing` | Existe no previous mas não no current (sumiu do servidor) | **preservada localmente** |

Cada run gera contadores desses 4 estados em `reconcile_log.jsonl`.

---

## Termos do parser canônico (Fase 2 do ChatGPT — `src/parsers/chatgpt.py`)

### Parquet canônico / `processed`

Saída do parser em `data/processed/<Source>/`. 4 tabelas (ChatGPT):
`conversations.parquet`, `messages.parquet`, `tool_events.parquet`,
`branches.parquet`. Schema definido em `src/schema/models.py`. Interface
universal consumida pelo dashboard descritivo (Quarto futuro) e pelo projeto
de análise qualitativa (`~/Desktop/AI Interaction Analysis/`).

### Branch

Caminho linear no `mapping` da conv. Conv sem fork tem 1 branch (`<conv>_main`).
Conv com fork (node com ≥2 children) tem N branches: a main vai do root até
o fork, cada child do fork começa uma sub-branch própria com
`parent_branch_id` apontando pra origem. `is_active=True` em exatamente 1
branch por conv (a que contém `current_node`). v2 ignorava forks off-path —
v3 preserva tudo.

### ToolEvent

Linha em `tool_events.parquet`. Representa uma operação não-conversacional:
busca (`search`), execução de código (`code`), canvas, deep research, geração
de imagem (`image_generation`), citação (`quote` = tether_quote), memória
(`bio`), file_search, computer_use, etc. Cada msg do raw com `author.role=tool`
vira um ToolEvent. A msg correspondente NÃO aparece em `messages.parquet`
(filtrada — só `role∈{user,assistant}` vira Message).

### is_preserved_missing / last_seen_in_server

Campos canônicos da Conversation derivados do `_last_seen_in_server` do raw:
`is_preserved_missing=True` quando `_last_seen_in_server` ≠ data da última
run conhecida no merged (idempotente, independente de `today`). Permite
downstream filtrar "convs ativas no servidor" vs "preservadas localmente"
sem reimplementar a heurística.

### Custom GPT vs Project (gizmo_id)

`gizmo_id` no raw mistura dois conceitos pelo prefixo:
- `g-p-*` → Project (pasta com sources). Vai pra `Conversation.project_id`.
- `g-*` (não `g-p-*`) → Custom GPT real. Vai pra `Conversation.gizmo_id`.

Empírico: ~1045 convs em projects, ~1 conv com Custom GPT real (na base atual).

---

## Outputs visíveis

### `LAST_CAPTURE.md` / `LAST_RECONCILE.md`

Snapshot human-readable da última run. Bate o olho e vê quando + counts. Sobrescrito a cada run.

### `capture_log.jsonl` / `reconcile_log.jsonl`

Histórico cumulativo, append-only — uma linha por run. Não pode ser reconstruído depois (sem backdating), por isso é gravado na hora de cada execução.

---

## Lembrete fundamental

> **Discovery pode baixar. Merged não.**

Se ver discovery caindo, é porque o servidor mudou. Se ver merged crescendo, é porque capturamos mais histórico. Se ver merged baixando — é bug e tem que investigar.

---

## Comportamento do servidor ChatGPT (validado empiricamente)

### `update_time` em rename de conv

O servidor **bumpa `update_time` para a hora atual** quando renomeias um chat pela sidebar. Validado em 2026-04-28 com 2 chats antigos (out/2025 e mai/2025) — ambos saltaram para 2026-04-28 ao serem renomeados.

**Implicação:** rename é detectado pelo caminho incremental normal (`update_time > cutoff` força refetch). O guardrail extra no código (`_filter_incremental_targets` comparando `title` da discovery vs `prev_raw`) é defesa em profundidade caso o comportamento mude.

### Rename de project

Sempre detectado, independente de `update_time`. O `project_names` é re-fetched a cada run (via DOM scrape ou API). Como `_project_name` é injetado em todas as convs do project no enrichment, o reconciler detecta mudança via diff de campos `_*`.

### `/projects` 404 intermitente

A discovery tem fallback automático: `/projects` → `/gizmos/discovery/mine` → DOM scrape do sidebar. Fail-fast só dispara se TODOS falharem juntos (raro). Aceita captura parcial só quando explicitamente em última instância (e ainda assim, se a captura cair >20% do baseline histórico, aborta).
