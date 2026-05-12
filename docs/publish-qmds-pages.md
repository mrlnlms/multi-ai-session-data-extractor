# Publicar qmds renderizados — discutido, adiado

Discussao em 2026-05-12 sobre publicar os HTMLs do Quarto (`notebooks/_output/`)
em GitHub Pages, integrado ao ciclo do dashboard Streamlit (botao que faz
sync → parse → unify → dvc push → git push → render → publish).

## Estado atual

- HTMLs sao gitignored (`*.html` + `notebooks/_output/` no `.gitignore`).
- Renderizacao acontece local via `quarto render notebooks/<plat>.qmd` com
  `QUARTO_PYTHON="$(pwd)/.venv/bin/python"`.
- Servidos local pelo Streamlit (`static/quarto/`) e pelo `serve-qmds.sh`.
- `_quarto.yml` usa `embed-resources: true` — HTML injeta os dados inline.
- `.github/workflows/` tem so `test.yml` (CI de testes). Sem workflow de publish.

## Referencia consultada

`~/Desktop/whatsapp-interaction-analysis/.github/workflows/publish.yml` —
workflow oficial de Quarto Publish (65 linhas):

- Trigger `push: [main]` + `workflow_dispatch`
- Setup python + quarto-actions + r-lib (pacotes R: tidyverse, plotly, etc)
- `pip install -e ".[notebooks]"` + ipykernel
- `quarto render` + `upload-pages-artifact` + `deploy-pages`
- Renderiza com `DATA_FOLDER=sample` — sample sintetico commitado em
  `data/raw/sample/` + `data/processed/sample/` (whitelist no .gitignore
  com `!data/raw/sample/`). Pages dele eh demo publico, nao dado real.

## Problema bloqueador

Repo eh publico. Os parquets reais contem mensagens pessoais (1171 convs
ChatGPT, 24k msgs Claude.ai, etc) e `embed-resources: true` injeta tudo
inline nos HTMLs. Render local + commit HTMLs no repo publico = exposicao
permanente:

- Git mantem historico; `git rm` + push nao apaga commits anteriores.
- Apagar pra valer exige rewrite history (BFG / filter-branch) + force push,
  e mesmo assim Wayback Machine, Google cache e forks ja podem ter copiado.

## Tres caminhos avaliados

**A. Render local, CI so copia pro Pages.** Botao Streamlit renderiza no
Mac (onde parquets reais existem), commita HTMLs em pasta tipo `docs/`,
push, workflow simples sobe pra Pages. Dado pessoal vai pro repo publico.
**Rejeitado** — exposicao permanente.

**B. Render no CI com `dvc pull`.** Workflow tem secret de service account
do gdrive, baixa parquets, renderiza. Mesmo resultado final no Pages: dado
pessoal publico. Limite do runner GitHub eh 14GB disco — parquets atuais
~16GB podem estourar (mitigavel com pull seletivo de `data/unified/`).
**Rejeitado** — exposicao permanente + parquets grandes.

**C. Render local com sample sintetico, CI roda com sample.** Igual whatsapp.
Gerar `data/processed/sample/` com dado fake/anonimizado, commitar no repo.
Pages vira demo publico do tool, dado real fica so local. Mais trabalho
upfront (sample que faca os qmds renderizarem sem quebrar).

## Decisao

**Adiado.** Quando retomar, decisao pendente eh entre:

1. **GitHub Pages com mock sintetico (caminho C)** — vitrine publica do tool,
   estilo whatsapp. Gera `data/processed/sample/` whitelisted no .gitignore,
   workflow renderiza com sample, dado real nunca sai do Mac.

2. **Tailscale ou Cloudflare Tunnel no Streamlit local** — acesso remoto
   privado aos qmds reais. ~10min de setup, ninguem alem do user ve. Resolve
   o caso "quero acessar de outro device" sem expor.

A escolha depende do objetivo real (vitrine publica vs acesso remoto privado),
que ficou sem definicao na conversa.

## Notas operacionais (pra quando retomar)

- Se for C: o workflow do whatsapp eh um bom template. Ajustar `pip install`
  pras deps deste projeto, remover setup-r (nao usamos R), apontar pra
  `notebooks/*.qmd` corretos.
- Integracao com dashboard Streamlit: o botao "rodar ciclo" no Streamlit
  faria subprocess local ate `git push`; daqui o workflow dispara sozinho
  via trigger `push: [main]`. Nao precisa logica extra de "trigger publish"
  no Streamlit.
- `embed-resources: true` continuaria valido com mock — sample sintetico
  inline eh trivial.
