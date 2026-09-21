# Glossario — operacao e DVC

Termos usados ao recuperar, publicar e reter a base de dados. O procedimento
completo esta no [DVC runbook](dvc-runbook.md).

## Ponteiro DVC

Arquivo pequeno versionado pelo Git que descreve uma saida grande em `data/`.
O conteudo real fica no remoto DVC, nao no Git.

## Remote

Armazenamento configurado para os objetos DVC. O remoto operacional atual e o
Google Drive; ele guarda a base canonica atual recuperavel.

## Checkout de dados

A materializacao local dos objetos DVC em `data/`. Pode ser removida para
liberar espaco e reconstruida com `dvc pull`.

## Estado duravel e projecao do asset vault

No asset vault, `schema.json`, os blobs content-addressed e os
`records.jsonl` commitados formam o estado duravel. `state.json`, hardlinks de
compatibilidade e Parquets sao projecoes reconstruiveis. Esse contrato foi
validado, publicado no DVC e verificado contra o remoto como fonte canonica. Um
novo restore frio fica reservado como diagnostico de recuperacao; a confirmacao
operacional foi confirmada por coletas incrementais reais. A auditoria de
retencao retirou de `raw` e `merged` apenas as copias comprovadas no vault;
registros e manifests permanecem preservados. `data/external/` e uma fronteira
separada para inputs fora da captura automatizada regular: adaptadores podem
le-los, mas a retencao do vault nao os percorre nem reclassifica. Veja a
[transicao operacional](pipeline.md#transicao-do-asset-vault).

## Rollback de asset

Recuperacao integral dos bytes a partir de uma revisao DVC anterior. O modo
`legacy` continua util para compatibilidade e diagnostico, mas, depois da
retencao dos duplicados, nao e uma segunda copia completa dos assets. Registros
e manifests em raw/merged continuam preservados.

## Cache DVC

Objetos locais em `.dvc/cache/`, usados pelo DVC para evitar transferencias e
duplicacao. Nao e fonte de verdade e nao deve ser sincronizado pelo Drive;
pode ser reconstruido.

## `dvc pull` e `dvc push`

`dvc pull` baixa a base apontada pelo checkout atual. `dvc push` envia ao
remoto os objetos adicionados e validados localmente. O push e uma publicacao
externa deliberada, feita junto com os ponteiros correspondentes no Git.

## Retencao e `dvc gc`

Retencao define quais objetos antigos permanecem recuperaveis. `dvc gc` e a
manutencao que remove objetos fora dessa politica; pode tornar dados apontados
por commits antigos irrecuperaveis. Nunca e etapa automatica de coleta:
exige simulacao, revisao e autorizacao explicita.

## `.dvc/config.local`

Configuracao local, fora do Git, que pode conter o segredo OAuth do remoto.
O backup privado e a restauracao pessoal ficam em `private/SETUP-PRIVADO.md`.
