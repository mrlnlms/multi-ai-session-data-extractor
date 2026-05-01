# Qwen — comportamento do servidor (validado empiricamente)

Espelho de `Comportamento do servidor ChatGPT` no CLAUDE.md. CRUD diff
sobre **4 snapshots** (3 do projeto-pai + 1 atual), 2026-04-24 → 2026-05-01.

| Snapshot | Chats |
|---|---|
| Qwen Data/2026-04-24T16-10 | 109 |
| Qwen Data/2026-04-24T17-47 | 109 |
| Qwen Data/2026-04-24T17-48 | 112 |
| current (2026-05-01) | 115 |

## CRUD entre snapshots consecutivos

| Transicao | Added | Removed | Renamed | Pin changed | updated_at bumped |
|---|---|---|---|---|---|
| 16-10 → 17-47 | 0 | 0 | 0 | 0 | 0 |
| 17-47 → 17-48 | 3 | 0 | 0 | 0 | 0 |
| 17-48 → current | 3 | 0 | 0 | 0 | 0 |

## Inferencias

- **Add funcionando:** 6 novos chats criados ao longo de 7 dias detectados
- **Sem deletes nesta janela:** preservation pattern nao foi exercitado.
  Quando user deletar, validar com bateria UI.
- **Sem rename/pin/archive nesta janela:** behavior mais granular (rename
  bumpa updated_at? archive expoe flag?) so dara pra confirmar com UI manual.
- **`updated_at` nao bumpou em chats existentes:** comportamento esperado
  porque tambem nao houve atividade neles. Ainda nao sabemos se rename
  bumpa — TODO bateria.

## Schema: features confirmadas presentes

- ✅ `pinned`: bool no schema raw + parser
- ✅ `archived`: bool no schema raw + parser (nesta base 0 archived)
- ✅ `project_id`: 3 chats em projects (Teste IA Interaction, Qualia, Travel)
- ✅ `share_id`: campo no schema, **0 valores nesta base** — feature
  existe na UI mas nao testada
- ✅ `folder_id`: campo no schema, **0 valores nesta base** — folders
  feature existe na UI mas nao testada
- ✅ 8 `chat_type`: t2t / search / deep_research / t2i / t2v / artifacts /
  learn / null

## Pendencias (requerem UI do usuario)

- [ ] **Rename:** `updated_at` bumpa no servidor?
- [ ] **Delete via menu:** chat some completamente OU vai pra archived?
- [ ] **Pin/unpin:** flag `pinned` no discovery reflete imediatamente?
- [ ] **Archive:** flag `archived` reflete? esta no listing principal ou
  separado?
- [ ] **Share:** populando `share_id` cria URL publica?
- [ ] **Move pra folder:** chats em folder retornam em listing default ou
  precisam filtro por `folder_id`?
- [ ] **Move pra project:** behavior do `project_id` quando muda

Bateria manual a documentar aqui quando rodar.
