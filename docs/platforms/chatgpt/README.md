# ChatGPT

ChatGPT é a **plataforma de referência** do projeto — todo o resto foi
modelado a partir dela. Por isso, a documentação detalhada não está aqui:

## Onde a info real mora

- **Arquitetura, sync 5 etapas, comportamento do servidor:** `CLAUDE.md`
  seção "Estado validado em 2026-04-28" + "Comportamento do servidor
  ChatGPT (validado empiricamente)".
- **Parser canônico v3 (plan):** [`docs/parser-v3/plan.md`](../../parser-v3/plan.md)
- **Empirical findings (raw):** [`docs/parser-v3/empirical-findings.md`](../../parser-v3/empirical-findings.md)
- **Validação cruzada v2 vs v3:** [`docs/parser-v3/validation.md`](../../parser-v3/validation.md)
- **Quarto data profile:** `notebooks/chatgpt.qmd`

## Por quê não tem `server-behavior.md` aqui

Quando o ChatGPT foi shipado (2026-04-28), o conceito de "doc por
plataforma" ainda não existia formalmente. As 6 plataformas que vieram
depois (Claude.ai, Qwen, DeepSeek, Perplexity, Gemini, NotebookLM) ganharam
seus próprios `server-behavior.md`. ChatGPT continua na referência viva
do CLAUDE.md.
