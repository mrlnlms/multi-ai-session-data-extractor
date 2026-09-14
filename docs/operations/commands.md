# Operational command map

Este e o indice curto dos comandos executaveis do projeto, inclusive os que
nao fazem parte da rotina diaria. Todos sao modulos Python importaveis em
`src/`; detalhes e precaucoes ficam nos runbooks indicados.

Use o prefixo abaixo a partir da raiz do repositorio:

```bash
PYTHONPATH=. .venv/bin/python -m <module>
```

## Captura por fonte

Fontes web oferecem `login`, `sync` e `parse`; fontes CLI oferecem `sync` e
`parse`. O sync web captura e reconcilia, mas seu parse e separado. O sync das
CLIs ja copia e parseia.

```bash
python -m src.platforms.chatgpt.commands.login
python -m src.platforms.chatgpt.commands.sync
python -m src.platforms.chatgpt.commands.parse
python -m src.platforms.codex.commands.sync
```

As flags, requisitos de browser e particularidades de cada fonte ficam em
`docs/extractor-engineering/platforms/<web|cli>/<source>/state.md`.

O inventario tecnico de contas e lido por `src/accounts.py` a partir dos
defaults compativeis, do registro privado, dos profiles e das arvores
raw/merged preservadas. Essas evidencias nao validam autenticacao e nao mudam
quais contas cada comando seleciona: Gemini e NotebookLM continuam executando
suas tres contas por default; os demais comandos preservam seus defaults.

## Workflows transversais

| Finalidade | Comando | Quando usar |
|---|---|---|
| Pipeline sem Streamlit | `python -m src.workflows.headless --no-publish` | Rodada automatizada; sem `--no-publish`, publica via DVC e Git |
| Unificar Parquets | `python -m src.workflows.unify` | Depois que os Parquets por fonte estiverem atuais |
| Importar saves manuais | `python -m src.workflows.manual_saves` | Quando houver clippings, copy/paste ou renders de terminal em `data/external/manual-saves/` |
| Servir relatorios | `python -m src.workflows.serve_reports open` | Depois de renderizar os HTMLs Quarto |
| Snapshot de configuracoes CLI | `python -m src.capture.cli.snapshot` | Preservar versoes sanitizadas de skills, hooks e configuracoes locais |

Manual saves nao substituem a captura oficial. Eles geram arquivos
`<source>_manual_<table>.parquet` na pasta processada da plataforma e sao
incluidos pela unificacao. Consulte `src/importers/manual/` para os formatos
aceitos.

## Operacoes excepcionais

O GC de DVC remove objetos historicos do remoto e nunca e etapa automatica:

```bash
python -m src.operations.dvc_gc plan
python -m src.operations.dvc_gc run --apply
python -m src.operations.dvc_gc resume .runtime/dvc-gc/<data-hora> --apply
```

Leia primeiro [dvc-runbook.md](dvc-runbook.md). A execucao com `--apply` exige
estado canonico publicado e autorizacao explicita.

Recuperacoes especificas permanecem com sua plataforma. Por exemplo:

```bash
python -m src.platforms.antigravity_cli.commands.recover_legacy --all-opaque
```

Probes empiricos ficam em `src/platforms/<source_id>/probes/`; nao sao comandos
de coleta rotineira.
