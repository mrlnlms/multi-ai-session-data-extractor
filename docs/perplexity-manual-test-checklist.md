# Perplexity — checklist de teste manual (HISTÓRICO)

> **Status: superado pela bateria CRUD UI executada em 2026-05-01.**
>
> Este doc foi escrito em 2026-04-29 como roteiro pré-shipping pra dissecar
> features e cobrir gaps. Todas as fases foram executadas (com adaptações)
> durante a bateria de 2026-05-01 com conta Pro. Resultados consolidados em:
>
> - `docs/perplexity-audit-findings.md` — bateria UI 2026-05-01 (achados empíricos)
> - `docs/perplexity-journey-2026-05-01.md` — 10 lições transferíveis
> - `docs/perplexity-pending-validations.md` — Pro/Max features (TODO público) + limitações upstream
>
> Mantido como referência histórica do approach exploratório. **Não usar
> como fonte de verdade pra estado atual.**

---

## Fases originais (todas concluídas)

- ✅ **Fase 1** — Validar fixes implementados (pinned threads, endpoints de spaces, upload em Space)
- ✅ **Fase 2** — Cobrir tipos de thread (Deep Research, Pro Search, Computer mode → resultou em descobrir mode `ASI`)
- ✅ **Fase 3** — Validar share, voice, archive (share funciona / voice tem áudio descartado upstream / archive é Enterprise-only)
- ✅ **Fase 4** — Skills em spaces (descoberto endpoint `/rest/skills?scope=collection&scope_id=<UUID>`)

Para detalhes do que cada fase descobriu, ver `perplexity-audit-findings.md`.
