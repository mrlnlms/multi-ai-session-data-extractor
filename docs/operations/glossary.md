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
