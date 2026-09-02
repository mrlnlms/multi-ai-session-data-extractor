# CLAUDE.md — guia operacional para Claude Code

## Projeto

Este projeto e a fonte canonica de captura e preservacao de sessoes de IA:
9 plataformas web (ChatGPT, Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek,
Perplexity, Grok e Kimi) e 4 CLIs (Claude Code, Codex, Gemini CLI e
Antigravity CLI).

Fluxo canonico:

```text
extractor/copy -> raw -> reconciler -> merged -> parser -> processed -> unify -> unified
```

Ele publica Parquets unificados para consumo downstream. Mudancas no schema
ou nos Parquets publicados exigem revisao deliberada dos impactos antes da
publicacao.

Antes de alterar extractor, reconciler ou parser, leia `README.md`,
`docs/README.md` e o
`docs/extractor-engineering/platforms/<web|cli>/<source>/state.md`
correspondente. O codigo e os dados observaveis prevalecem sobre registros
historicos.

## Limites de preservacao e privacidade

1. Capturar uma vez, nunca rebaixar: downloaders reutilizam binarios ja
   existentes.
2. Registros ausentes no servidor sao preservados como `preserved_missing`.
3. Discovery parcial aciona `refetch_known`; nao deve contaminar `raw`.
4. `src/schema/models.py` e a fronteira entre captura e analise.
5. Dados pessoais ficam fora do Git. Trate `data/` e `.storage/` com cuidado.

`private/` e um symlink versionado para o workbench privado do proprietario,
fora do checkout. Use-o para documentos de bancada, midias-fonte, handoffs e
configuracoes privadas duraveis; o Git registra apenas o symlink. Nao adicione
seu conteudo ao indice e nao crie material novo em `docs/local/`, que esta em
curadoria gradual.

`.venv/`, `.storage/`, `.runtime/`, `.dvc/cache/` e o checkout `data/` sao
estado local descartavel ou recriavel, cada um com seu proprio contrato.

## Pipeline e validacao

- Scripts `<source>-sync.py` web fazem captura + assets + reconcile, mas nao
  chamam o parser quando executados diretamente.
- O dashboard/headless executa o `<source>-parse.py` depois de sync web
  bem-sucedido e antes de `scripts/unify-parquets.py`.
- Os syncs das CLIs ja fazem copy + parse.
- Alteracoes no schema unificado e nos Parquets publicados exigem revisao dos
  impactos em consumidores downstream antes da publicacao.
- Ao promover uma fonte, atualize `dashboard/data.py`, valide o dashboard
  Streamlit e os relatorios Quarto. Nao declare a pipeline verde se o parquet
  estiver anterior a `raw` ou `merged`.
- Rode a suite de testes antes de merge; nao fixe quantidades de testes na
  documentacao.
- Ao alterar um fato canonico (plataformas, contagem, comando, etapa de
  pipeline, status, retencao ou contrato publico), atualize a fonte primaria,
  pesquise a afirmacao antiga no codigo e na documentacao mantidos e corrija
  as superficies derivadas aplicaveis: ajuda/docstrings de CLI, README/indice,
  operations, dashboard, Quarto, `state.md` e limites conhecidos. Antes de
  encerrar, valide links locais e rode `git diff --check`.

Inicie o dashboard com:

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py
```

Quando descobrir uma feature em uma plataforma, teste-a empiricamente nas
outras e registre a conclusao em
`docs/extractor-engineering/cross-platform-validation.md`.

## DVC: base atual e espaco

O Google Drive e o remoto DVC operacional. O DVC guarda a base canonica atual
fora do Mac, com arquivos incrementais e deduplicados; ele nao e um compromisso
de manter para sempre todas as versoes historicas dos dados apontadas pelo Git.

O ciclo normal de uma atualizacao validada e:

```text
sync/copy -> reconcile -> parse -> unify -> dvc add -> commit -> dvc push -> git push
```

`dvc push` e `git push` sao escritas externas. Execute-os somente com pedido
explicito do usuario; uma execucao deliberada do dashboard com Publish marcado
e autorizacao valida do operador.

`dvc gc` e manutencao deliberada de espaco, nunca uma etapa automatica. Pode
tornar revisoes antigas de dados irrecuperaveis, mesmo que o codigo e seus
ponteiros continuem no Git. Antes de qualquer GC, a base atual precisa estar
validada, commitada e enviada; rode primeiro a simulacao e obtenha autorizacao
explicita para excluir. O procedimento exato esta em
`docs/operations/dvc-runbook.md`.

Uma alternativa ao Drive e pesquisa futura, nao uma migracao ativa nem motivo
para bloquear coleta ou publicacao normal.

## Investigacao por plataforma

- Os guardrails de discovery parcial e os fallbacks variam por plataforma;
  consulte o `state.md` antes de alterar discovery ou reconcile.
- Login sempre e headed e os perfis persistem em `.storage/`.
- O modo de captura e detalhes de Cloudflare/headless pertencem aos `state.md`
  e `server-behavior.md` de cada plataforma. Consulte-os antes de alterar
  autenticacao ou browser automation.
- Requisitos de download de assets e comportamentos de API pertencem a
  documentacao da plataforma; nao os simplifique sem nova validacao empirica.

## Comandos basicos

```bash
# Instalar dependencias da maquina atual
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# Testes
PYTHONPATH=. .venv/bin/pytest

# Materializar Parquets unificados apos parses
PYTHONPATH=. .venv/bin/python scripts/unify-parquets.py
```

Comandos de captura, login e diagnostico ficam no `state.md` de cada fonte.
Para restaurar um checkout apagado ou gerenciar espaco, use o [guia de
setup](docs/SETUP.md), o runbook DVC e o complemento privado
`private/SETUP-PRIVADO.md`.

## Convencoes

- Codigo e identificadores em ingles; documentacao pode seguir o idioma do
  arquivo existente.
- Commits usam Conventional Commits. Nao crie commit ou push sem pedido do
  usuario.
- Preserve mudancas preexistentes no worktree e nunca limpe dados apenas para
  “fazer o DVC bater”.
- `scripts/backup_to_dvc.sh` e legado; nao o use ate ser corrigido e validado.
