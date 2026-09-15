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
6. Perder, excluir ou abandonar uma conta upstream encerra novas capturas, mas
   nao autoriza remover seu acervo ja preservado. Mantenha o ultimo `raw` e
   `merged`, ou um snapshot imutavel em `data/external/` quando o formato for
   anterior ao pipeline atual; o parser oficial deve continuar materializando
   esse acervo com proveniencia historica explicita.

`private/` e um symlink versionado para o workbench privado do proprietario,
fora do checkout. Use-o para documentos de bancada, midias-fonte, handoffs e
configuracoes privadas duraveis; o Git registra apenas o symlink. Nao adicione
seu conteudo ao indice.

Planos de implementacao e outros documentos de trabalho devem ser criados
diretamente em `private/docs/discussions/`, sem pedir aprovacao separada para
salva-los. Quando o usuario exigir revisao ou aprovacao antes de alterar codigo,
esse gate se aplica a implementacao versionada e nao ao registro do plano no
workbench privado.

### Edicao segura atraves do symlink `private/`

O destino de `private/` fica fora da raiz gravavel do checkout. Ferramentas de
patch podem ler pelo symlink, mas normalmente nao conseguem escrever nele. Nao
tente `apply_patch` diretamente em `private/...` e nunca inclua um arquivo de
`private/` no mesmo patch que arquivos do repositorio: um patch multi-arquivo
pode aplicar parcialmente os arquivos internos antes de falhar no destino do
symlink, e uma repeticao pode duplicar mudancas.

Para editar um arquivo existente em `private/`, resolva o destino com
`readlink private`, copie o alvo para um snapshot original e uma copia de
trabalho em `/private/tmp`, edite a copia com `apply_patch`, revise `diff -u` e
use `cmp` para confirmar que o alvo nao mudou desde o snapshot. Entao faca uma
unica copia escalada da versao revisada para o path externo exato e releia o
arquivo pelo symlink. Para arquivo novo, prepare e revise o conteudo completo em
`/private/tmp` antes da unica copia escalada. A autorizacao para documentos de
trabalho privados continua implicita; a escalacao e apenas tecnica. Se `cmp`
detectar mudanca concorrente, nao sobrescreva: reinicie a partir do alvo atual.

`.venv/`, `.storage/`, `.runtime/`, `.dvc/cache/` e o checkout `data/` sao
estado local descartavel ou recriavel, cada um com seu proprio contrato.

Antes de classificar um registro tecnico legado como apenas privado, obsoleto
ou descartavel, compare suas afirmacoes com o codigo atual e com o `state.md`,
`discovery.md`, `server-behavior.md` e limites conhecidos da fonte. Promova
para a documentacao versionada os fatos duraveis que ainda faltarem, redigindo
identificadores pessoais quando necessario; preserve o original em `private/`
quando ele tambem contiver dados pessoais, logs de trabalho ou contexto datado.
Nao conclua que houve consolidacao apenas pelo nome, idade ou status do arquivo.

## Pipeline e validacao

- Cada fonte fica inteira em `src/platforms/<source>/`. Fontes web expoem
  modulos em `commands/` para login, sync e parse; fontes CLI expoem sync e
  parse. Probes empiricos ficam em `src/platforms/<source>/probes/`;
  ferramentas excepcionais especificas tambem ficam junto da plataforma.
  Comandos e implementacao de fluxos transversais ficam em
  `src/workflows/`; operacoes excepcionais do repositorio ficam em
  `src/operations/` e nao integram o pipeline normal.
- Interfaces Python executaveis, dashboard, entrypoints e testes reutilizam
  `src/`; nao manter uma arvore paralela em `scripts/`.
- O Streamlit em `dashboard/` e apenas o adaptador de apresentacao. Estado e
  perfis de dados ficam em `src/application/`; orquestracao do pipeline fica em
  `src/workflows/`. `src/` nao importa `streamlit` nem `dashboard`.
- `src/accounts.py` fornece o inventario somente leitura de contas para os
  callers da aplicacao. Registro privado, profile e dados raw/merged sao
  evidencias separadas; profile existente nao significa autenticacao valida.
  Esse inventario nao muda os alvos nem o comportamento atual do pipeline.
- `src/account_catalog.py` valida a identidade e o lifecycle arquivaveis em
  `data/accounts/catalog.json`, restaurados por DVC. O inventario preserva a
  uniao entre catalogo e evidencias, e nunca deriva lifecycle da autenticacao.
- Modulos `src.platforms.<source>.commands.sync` web fazem captura + assets + reconcile, mas nao
  chamam o parser quando executados diretamente.
- O dashboard/headless executa o `parse.py` da fonte depois de sync web
  bem-sucedido e antes de `python -m src.workflows.unify`.
- Os syncs das CLIs ja fazem copy + parse.
- Alteracoes no schema unificado e nos Parquets publicados exigem revisao dos
  impactos em consumidores downstream antes da publicacao.
- Ao promover uma fonte, atualize `src/platforms/registry.py`, valide o dashboard
  Streamlit e os relatorios Quarto. Nao declare a pipeline verde se o parquet
  estiver anterior a `raw` ou `merged`.
- Para alinhar produto e roadmap, comece pela linha de desenvolvimento em
  `docs/ROADMAP.md` e abra detalhes apenas da frente discutida. O core
  reutilizavel fica em `src/`, nao em Streamlit ou Quarto.
- Em uma nova sessao, consulte o baseline por
  `python -m src.operations.archive_assurance status` antes de levantar duvidas
  genericas sobre frescor ou publicacao. O registro completo fica em
  `.runtime/archive-assurance.json`, fora do Git. `status` compara o checkout
  local com o ultimo estado verificado sem DVC ou rede. Se o registro estiver
  ausente ou os dados tiverem mudado, informe isso objetivamente; execute
  `verify` somente quando a tarefa exigir nova verificacao profunda. `verify`
  confere entradas/Parquets, dados DVC, remoto e Git antes de renovar o
  registro; nao e etapa automatica de abertura de chat. Nao repita ressalvas
  abstratas quando o baseline registrado for atual.
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
PYTHONPATH=. .venv/bin/streamlit run dashboard/app.py
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

Uma alternativa ao Drive e pesquisa futura e nao prioridade de curto prazo,
migracao ativa ou motivo para bloquear coleta ou publicacao normal.

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
PYTHONPATH=. .venv/bin/python -m src.workflows.unify
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
