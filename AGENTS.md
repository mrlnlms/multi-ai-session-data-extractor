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
de alterar um extractor, reconciler ou parser. `CLAUDE.md` contem o guia
autonomo equivalente para Claude Code. As regras compartilhadas devem ficar
alinhadas; o estado observavel no codigo e nos dados prevalece sobre texto
historico.

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
- Este projeto e o pai/fonte canonica de captura. O projeto filho/consumidor
  `AI Interaction Analysis` le os Parquets unificados publicados daqui.
  Mudancas de schema unificado devem ser coordenadas com ele antes da
  publicacao.
- Toda plataforma promovida deve aparecer em `dashboard/data.py`, no dashboard
  Streamlit e nos relatorios Quarto. O dashboard e iniciado por
  `PYTHONPATH=. .venv/bin/streamlit run dashboard.py`.
- Nao declarar uma pipeline verde se o parquet for anterior ao raw/merged.
- Rodar a suite de testes antes de merge; nao manter contagem fixa de testes
  na documentacao, pois parametrizacoes alteram esse numero.

## DVC e retencao

O Google Drive e o remoto DVC operacional da base canonica atual. O DVC e
usado para armazenar, deduplicar e recuperar os dados grandes sem mante-los no
Mac; a retencao de cada revisao historica dos dados nao e um requisito do
produto.

- `dvc push` faz parte normal da publicacao de uma atualizacao validada. Um
  agente so pode executa-lo com autorizacao explicita do usuario; uma execucao
  deliberada do dashboard com Publish marcado e uma autorizacao valida do
  operador.
- `dvc gc` e manutencao deliberada de espaco, nunca uma etapa automatica. Ele
  pode tornar revisoes antigas de dados irrecuperaveis, embora o historico do
  codigo continue no Git. Antes de qualquer limpeza: confirmar que o estado
  canonico atual esta commitado e enviado, executar primeiro em modo seco e
  obter autorizacao explicita do usuario para a exclusao.
- Uma alternativa ao Drive continua sendo pesquisa futura, nao uma migracao ou
  bloqueio operacional em andamento.

## Convencoes

- Codigo e identificadores em ingles; documentacao pode permanecer no idioma
  existente do arquivo.
- Commits usam Conventional Commits. Nao criar commit ou push sem pedido do
  usuario.
- Preservar mudancas preexistentes no worktree e nunca limpar dados para
  "fazer o DVC bater".
- `scripts/backup_to_dvc.sh` e legado e nao representa o conjunto atual de
  dados; nao usa-lo ate ser corrigido e validado.
