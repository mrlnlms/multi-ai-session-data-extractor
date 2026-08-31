# AGENTS.md — instrucoes canonicas para agentes

## Contexto

Este projeto captura e preserva sessoes de IA de 13 fontes: 9 plataformas
web (ChatGPT, Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity,
Grok e Kimi) e 4 CLIs (Claude Code, Codex, Gemini CLI e Antigravity CLI).

O fluxo canonico e:

```text
extractor/copy -> raw -> reconciler -> merged -> parser -> processed -> unify -> unified
```

Leia tambem `README.md`, `docs/README.md` e o `state.md` da plataforma antes
de alterar um extractor, reconciler ou parser. `CLAUDE.md` preserva contexto
historico e instrucoes detalhadas para Claude Code; em caso de divergencia,
este `AGENTS.md` e o estado observavel no codigo/dados prevalecem.

## Estado da recuperacao

A reconciliacao do backup foi concluida em 2026-08-29. A arvore promovida
combina o snapshot DVC de 2026-05-16 com a camada local posterior de
2026-05-19 e foi validada por caminho e SHA-256. O procedimento, os
manifestos e os caminhos de rollback estao em `docs/RECOVERY.md`.

O bloqueio temporario de coleta e processamento foi removido. O snapshot DVC
reconciliado foi enviado ao Google Drive em 2026-08-29 e `dvc status -c`
confirmou que cache e remoto estao sincronizados. Ate a migracao para
Cloudflare R2, o Google Drive legado pode ser usado como remoto transitorio,
mas todo novo `dvc push` exige autorizacao explicita do usuario. Nunca executar
`dvc gc` durante essa transicao.

## Principios de preservacao

1. Capturar uma vez, nunca rebaixar: downloaders pulam binarios existentes.
2. Preservar registros ausentes no servidor como `preserved_missing`.
3. Discovery parcial aciona `refetch_known`; nao deve contaminar o raw.
4. O schema em `src/schema/models.py` e a fronteira entre captura e analise.
5. Dados pessoais ficam fora do Git; `data/` e `.storage/` exigem cuidado.

## Acervo privado

`private/` e um symlink versionado para o workbench privado do proprietario,
fora deste checkout e sincronizado separadamente. Ele e a casa de documentos
de bancada, planos, probes, handoffs, midias-fonte e outros artefatos
duraveis que nao pertencem ao projeto publicavel. O Git registra somente o
symlink; nunca adicionar seu conteudo ao indice.

Nao criar novo material em `docs/local/`: a pasta legada sera curada e
migrada gradualmente para `private/`. `data/`, `.dvc/cache/`, `.storage/` e
artefatos renderizados continuam tendo seus proprios contratos de DVC ou de
estado local; nao devem ser movidos para o workbench privado por conveniencia.

## Pipeline e validacao

- Os scripts `<source>-sync.py` das fontes web fazem captura + assets +
  reconcile e nao chamam o parser quando executados diretamente. O pipeline
  do dashboard/headless executa automaticamente o `<source>-parse.py` depois
  de cada sync web bem-sucedido e antes de `scripts/unify-parquets.py`.
- Os syncs das 4 CLIs ja fazem copy + parse.
- `data/unified/` possui atualmente 13 parquets: 4 canonicos e 9 auxiliares.
- Mudancas de schema unificado devem ser coordenadas com o projeto consumidor
  `AI Interaction Analysis` antes de publicar os dados.
- Toda plataforma promovida deve aparecer em `dashboard/data.py`, no dashboard
  Streamlit e nos relatorios Quarto. O dashboard e iniciado por
  `PYTHONPATH=. streamlit run dashboard.py`.
- Nao declarar uma pipeline verde se o parquet for anterior ao raw/merged.
- Rodar a suite de testes antes de merge; nao manter contagem fixa de testes
  na documentacao, pois parametrizacoes alteram esse numero.

## Convencoes

- Codigo e identificadores em ingles; documentacao pode permanecer no idioma
  existente do arquivo.
- Commits usam Conventional Commits. Nao criar commit ou push sem pedido do
  usuario.
- Preservar mudancas preexistentes no worktree e nunca limpar dados para
  "fazer o DVC bater".
- `scripts/backup_to_dvc.sh` e legado e nao representa o conjunto atual de
  dados; nao usa-lo ate ser corrigido e validado.
