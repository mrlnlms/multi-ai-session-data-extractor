# Documentacao

Mapa curto da documentacao do projeto. Use o documento do tema em vez de ler
tudo: o [README da raiz](../README.md) apresenta o produto e `AGENTS.md`
define as regras de trabalho para agentes.

## Fundamentos do projeto

- [SETUP.md](SETUP.md) — instalar, retomar um acervo e fazer a primeira
  coleta.
- [SECURITY.md](SECURITY.md) — credenciais, dados pessoais e cuidados antes
  de publicar.
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribuicao e adicao de plataformas.
- [ROADMAP.md](ROADMAP.md) — prioridades e decisoes abertas.

## Documentacao por tema

- [operations/](operations/) — operacao cotidiana: pipeline, dashboard,
  recuperacao/publicacao DVC, retencao e
  [mapa de comandos](operations/commands.md),
  [termos operacionais](operations/glossary.md), incluindo o
  [runbook de coleta web](operations/web-collection.md).
- [`data/external/README.md`](../data/external/README.md) — fronteira de
  preservacao para inputs manuais, exports e snapshots excepcionais fora da
  aquisicao automatizada regular.
- [extractor-engineering/](extractor-engineering/) — engenharia da captura,
  validacao cross-platform, [limites conhecidos](extractor-engineering/known-limitations.md)
  [pendencias de memoria web](extractor-engineering/web-memory-capture-backlog.md),
  [cobertura canonica de assets](extractor-engineering/asset-coverage.md) e
  [termos de captura](extractor-engineering/glossary.md), alem dos documentos
  tecnicos por plataforma. O contrato publica separadamente os escopos
  `preserved_web_files` e `preserved_cli_session_assets`.
- [product/](product/) — mapa da arquitetura da aplicacao e da transicao entre
  dashboard, leitor, curadoria e analise exploratoria; aponta para a visao do
  produto, a arquitetura de contas e o contrato do leitor.

Material privado e duravel pertence ao workbench apontado por `private/`.
