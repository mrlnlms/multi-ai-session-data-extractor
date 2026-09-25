# AGENTS.md — instrucoes canonicas para agentes

## Contexto

Este projeto captura e preserva sessoes de IA de 13 fontes: 9 plataformas
web (ChatGPT, Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity,
Grok e Kimi) e 4 CLIs (Claude Code, Codex, Gemini CLI e Antigravity CLI).

O fluxo canonico tem duas entradas e um vault de assets compartilhado:

```text
web: extractor -> raw -> reconciler -> merged -> parser ┐
CLI: copy cumulativo -> raw -> parser                    ├-> processed -> unify -> unified
assets imutaveis -> data/assets (vault) <----------------┘
```

Leia tambem `README.md`, `docs/README.md` e o
`docs/extractor-engineering/platforms/<web|cli>/<source>/state.md` da fonte
antes de alterar um extractor, reconciler ou parser. O guia historico de Claude
Code foi preservado em `private/CLAUDE.md`; o estado observavel no codigo e nos
dados prevalece sobre texto historico.

Na frente de memoria/configuracao das plataformas web, registre as superficies
conhecidas que ainda nao foram capturadas e a evidencia necessaria para retoma-las
em `docs/extractor-engineering/web-memory-capture-backlog.md`. Atualize esse
documento ao concluir ou descobrir uma pendencia; detalhes tecnicos observados
continuam no `state.md` da respectiva plataforma.

## Principios de preservacao

1. Capturar uma vez, nunca rebaixar: uma entrega ja comprovadamente preservada
   nao deve ser baixada nem substituida por uma representacao pior. No modo
   `vault`, staging transitorio pode ser retirado somente depois de verificar o
   blob content-addressed gravado em `data/assets`.
2. Preservar registros conhecidos que desaparecem da origem como
   `preserved_missing`; ausencia upstream/local nunca autoriza apagar o raw.
3. Discovery parcial nao deve contaminar o raw nem produzir ausencias falsas.
   Use o fallback documentado da plataforma, como `refetch_known`, quando ele
   existir.
4. O schema em `src/schema/models.py` e a fronteira entre captura e analise.
5. Conteudo pessoal nao entra diretamente no Git. Dados canonicos em `data/`
   sao geridos por DVC; credenciais, profiles, bindings e auth health ficam em
   `.storage/`, fora de Git e DVC.
6. Perder, excluir ou abandonar uma conta upstream encerra novas capturas, mas
   nao autoriza remover seu acervo ja preservado. Mantenha o ultimo `raw` e
   `merged`, ou um snapshot imutavel em `data/external/` quando o formato for
   anterior ao pipeline atual; o parser oficial deve continuar materializando
   esse acervo com proveniencia historica explicita.

## Acervo privado

`private/` e um symlink versionado para o workbench privado do proprietario,
fora deste checkout e sincronizado separadamente. Ele e a casa de documentos
de bancada, planos, probes, handoffs, midias-fonte e outros artefatos
duraveis que nao pertencem ao projeto publicavel. O Git registra somente o
symlink; nunca adicionar seu conteudo ao indice.

Use `private/` somente para material privado e duravel. Nao crie plano, tracker,
handoff ou diario por padrao: para pedidos diretos, inspecione, implemente,
valide e responda. Crie acompanhamento em `private/docs/discussions/` apenas
quando o usuario pedir, houver tracker ativo relevante ou a frente realmente
precisar atravessar sessoes; registre somente fatos demonstrados.

Documentos historicos do workbench sao evidencia, nao instrucoes automaticas.
Antes de reutiliza-los, confronte-os com o codigo, a documentacao mantida e os
dados atuais. Decisoes duraveis devem ser promovidas para a documentacao
versionada apropriada; detalhes pessoais e registros datados permanecem
privados.

### Edicao segura atraves do symlink `private/`

O destino de `private/` fica fora da raiz gravavel do checkout. Antes de
escrever, resolva-o com `readlink private` e use uma operacao isolada do patch
do repositorio. Se precisar de copia intermediaria, use um diretorio temporario
exclusivo, compare antes de sobrescrever e remova-o ao terminar. Nunca adicione
o conteudo de `private/` ao indice do Git.

`data/`, `.dvc/cache/`, `.storage/` e artefatos renderizados continuam tendo
seus proprios contratos de DVC ou de estado local; nao devem ser movidos para
o workbench privado por conveniencia.

Antes de classificar um registro tecnico legado como apenas privado, obsoleto
ou descartavel, comparar suas afirmacoes com o codigo atual e com o `state.md`,
`discovery.md`, `server-behavior.md` e limites conhecidos da fonte. Promover
para a documentacao versionada os fatos duraveis que ainda faltarem, redigindo
identificadores pessoais quando necessario; preservar o original em `private/`
quando ele tambem contiver dados pessoais, logs de trabalho ou contexto datado.
Nao concluir que houve consolidacao apenas pelo nome, idade ou status do
arquivo.

## Pipeline e validacao

- Cada fonte fica inteira em `src/platforms/<source>/`. Fontes web expoem
  modulos em `commands/` para login, sync e parse; fontes CLI expoem sync e
  parse. Probes empiricos ficam em `src/platforms/<source>/probes/`;
  ferramentas excepcionais especificas tambem ficam junto da plataforma.
  Comandos e implementacao de fluxos transversais automaticos ficam em
  `src/workflows/`; comandos explicitos do operador que nao compoem o pipeline
  automatico ficam em `src/operations/`, sejam rotineiros ou excepcionais.
- Interfaces Python executaveis, dashboard, entrypoints e testes reutilizam
  `src/`; nao manter uma arvore paralela em `scripts/`.
- O Streamlit em `dashboard/` e um adaptador de apresentacao: chamadas `st.*`
  ficam ali. Estado e acoes UI-neutral ficam em `src/application/`; ordem,
  gating, locks e publicacao do pipeline ficam em `src/workflows/`. Modulos em
  `src/` nao importam `streamlit` nem `dashboard`.
- `src/accounts.py` e a fonte somente leitura do inventario observavel de
  contas. Registro privado, profile local e arvores preservadas em raw/merged
  sao evidencias independentes; a existencia de profile nao comprova login
  valido. O workflow usa esse inventario para selecionar contas capturaveis e
  exclui lifecycle `disabled`, `historical` e archives dos alvos de sync.
- `src/account_catalog.py` valida a identidade e o lifecycle arquivaveis em
  `data/accounts/catalog.json`, restaurados por DVC. O inventario faz uma uniao
  lossless entre catalogo e evidencias: nenhum dos dois lados pode ocultar uma
  conta do outro, e lifecycle nunca e inferido da autenticacao.
- Bindings de UUID para profile e auth health sao estado local em `.storage/`;
  probes e confirmacoes sao explicitos. Mutacoes do catalogo passam por
  `src/account_service.py`; sync seletivo por UUID passa por
  `src/workflows/account_sync.py`. Nenhum desses estados locais entra nos
  Parquets publicados.
- Os modulos `src.platforms.<source>.commands.sync` das fontes web fazem
  captura + assets + reconcile e nao chamam o parser quando executados
  diretamente. O pipeline do dashboard/headless executa automaticamente o
  `parse.py` da fonte depois de cada sync web bem-sucedido e antes de
  `python -m src.workflows.unify`.
- Os syncs das 4 CLIs fazem copy cumulativo + parse. A copia nunca deleta do
  raw. Quando a arvore HOME e observavel, o parser compara os arquivos atuais
  com os preservados e marca `is_preserved_missing=True` nas conversas cuja
  origem desapareceu; se a origem inteira estiver ausente ou vazia, preserva o
  raw sem inferir delecao.
- Este projeto publica o contrato de dados unificado. Mudancas de schema ou
  de Parquets publicados devem ter seus impactos em consumidores downstream
  revisados antes da publicacao.
- Toda plataforma promovida deve aparecer em `src/platforms/registry.py`, no dashboard
  Streamlit e nos relatorios Quarto. O dashboard e iniciado por
  `PYTHONPATH=. .venv/bin/streamlit run dashboard/app.py`.
- Nao declarar uma pipeline verde se o Parquet for anterior aos inputs
  canonicos aplicaveis, como raw, merged, catalogo ou estado duravel do vault.
- Para discutir prioridades ou planejar uma frente, consulte `docs/ROADMAP.md`
  e aprofunde apenas o tema em pauta; nao e leitura obrigatoria ao iniciar toda
  sessao. Use o status registrado ali como sinal normal de andamento e confira
  codigo, dados ou baseline quando houver contradicao ou a tarefa exigir
  verificacao. A reestruturacao move o core reutilizavel para `src/`, nao torna
  Streamlit ou Quarto o produto.
- Em uma nova sessao, o hook `SessionStart` em `.codex/` apresenta o baseline
  local do acervo. Se precisar rele-lo, use
  `.venv/bin/python -m src.operations.archive_assurance status`. Um baseline
  atual encerra duvidas genericas sobre frescor ou publicacao, sem consultar
  DVC ou rede. Se estiver ausente ou indicar
  dados alterados, informe o fato sem presumir falha do vault. Rode `verify`
  somente quando a tarefa exigir nova verificacao profunda, nunca como etapa
  automatica de abertura de chat. Procedimento e limites:
  `docs/operations/pipeline.md#baseline-de-validacao-entre-sessoes`.
- Rodar a suite de testes antes de merge; nao manter contagem fixa de testes
  na documentacao, pois parametrizacoes alteram esse numero.
- Ao alterar um fato canonico (plataformas, contagem, comando, etapa de
  pipeline, status, retencao ou contrato publico), atualizar a fonte primaria,
  buscar a afirmacao antiga no codigo e na documentacao mantidos e corrigir as
  superficies derivadas aplicaveis: ajuda/docstrings de CLI, README/indice,
  operations, dashboard, Quarto, `state.md` e limites conhecidos. Antes de
  encerrar, validar links locais e rodar `git diff --check`.

## DVC e retencao

O Google Drive e o remoto DVC operacional da base canonica atual. O DVC
armazena, deduplica e recupera dados grandes sem exigir que todo o acervo fique
materializado ou em cache no Mac; reter cada revisao historica dos dados nao e
requisito do produto.

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
  bloqueio operacional em andamento, nem prioridade de curto prazo.

## Convencoes

- Codigo e identificadores em ingles; documentacao pode permanecer no idioma
  existente do arquivo.
- Trabalhe de forma proporcional ao pedido: nao transforme revisao, limpeza ou
  correcao localizada em uma frente de planejamento sem necessidade explicita.
- Antes de apagar caches ou temporarios, diferencie residuos regeneraveis de
  dados preservados, estado operacional e evidencia de captura. Nunca trate
  `data/`, `.storage/`, `.dvc/cache/` ou `.runtime/archive-assurance.json` como
  lixo generico.
- Commits usam Conventional Commits. Nao criar commit ou push sem pedido do
  usuario.
- Preservar mudancas preexistentes no worktree e nunca limpar dados para
  "fazer o DVC bater".
