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

## Outputs visíveis

### `LAST_CAPTURE.md` / `LAST_RECONCILE.md`

Snapshot human-readable da última run. Bate o olho e vê quando + counts. Sobrescrito a cada run.

### `capture_log.jsonl` / `reconcile_log.jsonl`

Histórico cumulativo, append-only — uma linha por run. Não pode ser reconstruído depois (sem backdating), por isso é gravado na hora de cada execução.

---

## Lembrete fundamental

> **Discovery pode baixar. Merged não.**

Se ver discovery caindo, é porque o servidor mudou. Se ver merged crescendo, é porque capturamos mais histórico. Se ver merged baixando — é bug e tem que investigar.
