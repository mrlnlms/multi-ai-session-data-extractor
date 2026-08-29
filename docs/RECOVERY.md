# Recuperacao segura do backup de julho de 2026 — concluida

> **Status:** concluida em 2026-08-29. Este documento permanece como trilha
> de auditoria e guia de rollback.

## Situacao

A copia trazida do Google Drive nao corresponde integralmente ao ultimo
snapshot DVC. Ao mesmo tempo, ela contem capturas de 2026-05-19 posteriores
aos ponteiros DVC, atualizados em 2026-05-16. Nenhum dos dois lados deve
sobrescrever o outro.

Inventario observado em 2026-08-29:

| Area | Snapshot DVC | Copia local |
|---|---:|---:|
| `data/raw` | 22.693 arquivos / 7.672.351.085 bytes | 11.162 arquivos / 2.715.703.023 bytes |
| `data/merged` | 12.306 arquivos / 4.425.413.892 bytes | 1.285 arquivos / 428.083.264 bytes |
| `data/processed` | 90 arquivos / 202.602.662 bytes | 91 arquivos / 202.613.967 bytes |
| `data/unified` | 13 arquivos / 192.407.868 bytes | 13 arquivos / 192.413.400 bytes |

Ausencias confirmadas em `data/external/` incluem exports GDPR da OpenAI,
snapshots legacy do NotebookLM, snapshot do Grok e snapshots de configuracao
das CLIs.

## Regra principal durante a recuperacao

Nao executar `dvc pull` ou `dvc checkout` neste worktree. O estado local de
2026-05-19 pode ser sobrescrito pelo snapshot mais antigo de 2026-05-16.

## Procedimento executado

1. Congelar esta pasta como fonte local e gerar um inventario por caminho,
   tamanho e SHA-256.
2. Fazer um clone limpo do mesmo commit em um diretorio separado.
3. Restaurar o DVC apenas nesse clone, sem usar a pasta atual como cache ou
   destino.
4. Gerar o mesmo inventario no clone restaurado.
5. Classificar cada caminho como identico, apenas local, apenas DVC ou
   divergente.
6. Construir uma terceira arvore de recuperacao. Arquivos apenas locais e
   apenas DVC entram nela; divergencias sao resolvidas por semantica da
   plataforma, nunca apenas por data de modificacao.
7. Validar contagens de captura/reconcile, JSONs, binarios e parquets.
8. Reexecutar parsers web e `unify` somente sobre a arvore recuperada.
9. Rodar testes, smoke tests de schema, dashboard e Quarto.
10. Somente depois promover a arvore recuperada como novo estado canonico.

## Resultado da comparacao de 2026-08-29

O snapshot DVC foi restaurado integralmente em
`/Users/mosx/Desktop/ia-data/dvc-restore`, usando cache DVC isolado. `dvc
status` confirmou que dados e pipelines estao atualizados nesse clone. Os
manifestos completos ficaram em `/Users/mosx/Desktop/ia-data/comparison`.

Comparacao por caminho e SHA-256:

| Classe | Arquivos |
|---|---:|
| Identicos | 10.299 |
| Apenas no snapshot DVC | 24.679 |
| Apenas na copia local | 42 |
| Mesmo caminho, conteudo divergente | 2.314 |

A comparacao semantica reduziu as 2.314 divergencias a:

| Natureza | Arquivos | Decisao |
|---|---:|---|
| Apenas marcador operacional em JSON | 2.229 | versao local de 19/05 |
| Log JSONL com DVC como prefixo exato | 25 | versao local, que ja contem o historico DVC |
| JSON com mudanca de payload | 28 | versao local mais nova; snapshot DVC permanece preservado |
| Markdown operacional regeneravel | 22 | versao local mais nova |
| Parquet derivado | 9 | manter local como evidencia e regenerar depois |
| Apenas formatacao JSON | 1 | versao local |

Os sete Markdown aparentemente exclusivos de cada lado em `manual-saves`
tem bytes identicos. A diferenca esta apenas na representacao Unicode dos
acentos nos nomes (NFD na copia do Drive e NFC no DVC); a arvore reconciliada
usa os nomes NFC do snapshot. Arquivos `.DS_Store` nao entram na arvore
reconciliada.

## Regra de construcao da terceira arvore

1. Comecar pelo snapshot DVC completo, que contem os 24.679 arquivos ausentes
   da copia local.
2. Sobrepor arquivos da copia local, pois os marcadores e logs demonstram que
   ela representa a coleta posterior de 19/05.
3. Nao sobrepor `.DS_Store` nem os sete aliases NFD de `manual-saves`.
4. Preservar `dvc-restore` e a copia local sem alteracao. Assim, toda escolha
   de conflito continua reversivel e auditavel por SHA-256.
5. Gerar um novo manifesto da terceira arvore e provar que ela contem a uniao
   esperada antes de qualquer parser ou sincronizacao.

## Operacoes proibidas durante a recuperacao

- nova coleta ou login que altere `.storage/`;
- `dvc add`, `dvc push`, `dvc gc` ou publicacao pelo dashboard;
- exclusao de arquivos porque parecem duplicados;
- uso do estado interno copiado do DVC como prova de integridade;
- merge baseado apenas em `mtime`, que pode ter sido alterado pelo Drive.

## Condicao para encerrar a recuperacao

A recuperacao termina quando os inventarios forem reconciliados, os dados
mais novos forem preservados, os blobs historicos do DVC forem recuperados e
as validacoes do pipeline passarem. Nesse momento, remover o bloqueio
temporario de `AGENTS.md` em uma mudanca separada e revisavel.

## Promocao e validacao final

Em 2026-08-29, antes da promocao, a `data/` original foi clonada para:

`/Users/mosx/Desktop/ia-data/pre-promotion-local-2026-08-29/data`

Esse backup possuia 12.655 arquivos e foi validado contra o manifesto local
original. A arvore reconciliada foi entao promovida para este worktree. Depois
do push DVC e da confirmacao de sincronismo remoto, esse diretorio e o checkout
temporario `dvc-restore` foram removidos para liberar espaco. Seus manifestos
de auditoria permanecem em `/Users/mosx/Desktop/ia-data/comparison`.

Resultado final:

- 37.318 arquivos promovidos, identicos a arvore reconciliada por SHA-256;
- 37.210 arquivos de `raw`, `merged` e `external` revalidados depois do
  rebuild, sem ausencias, extras ou divergencias;
- 12.018 JSONs, 5.005 JSONLs e 103 Parquets validos;
- 13 tabelas unificadas, 527.864 linhas, sem PK nula ou duplicada;
- 683 testes passaram e 1 foi pulado;
- dashboard Streamlit renderizado sem excecoes;
- 22 de 22 relatorios Quarto renderizados.

O novo snapshot DVC foi criado localmente para `raw`, `merged`, `processed`
e `unified`; `dvc status` retorna `Data and pipelines are up to date`. Os 12
ponteiros de `external` nao mudaram. Durante a recuperacao, nenhum `dvc push`,
commit ou push Git foi executado. Depois do encerramento, 2.396 objetos do
baseline reconciliado foram enviados ao Google Drive e `dvc status -c`
confirmou que cache e remoto estavam em sincronia. O Drive permanece como
remoto transitorio; a migracao definitiva sera tratada separadamente.

Manifestos, ledger e relatorios de validacao ficam em:

`/Users/mosx/Desktop/ia-data/comparison`
