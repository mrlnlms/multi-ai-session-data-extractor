# Pipeline operations

Comandos cotidianos para capturar, processar e materializar os dados. Para
instalacao e login, use [SETUP.md](../SETUP.md). Para uma rodada web segura,
use [web-collection.md](web-collection.md). Regras de DVC e publicacao ficam
em [dvc-runbook.md](dvc-runbook.md).

```text
sync/copy -> raw -> reconcile -> parse -> processed -> unify -> unified
```

Use `PYTHONPATH=. .venv/bin/python` para executar scripts sem depender do
Python global.

## Atualizar uma fonte

Quando chamados diretamente, os nove syncs web executam captura, assets quando
aplicavel e reconcile; o parse correspondente deve vir depois. O dashboard e
o modo headless executam esse parse automaticamente após um sync web
bem-sucedido. Os quatro syncs de CLI ja fazem copy e parse.

```bash
# Fonte web: exemplo ChatGPT
PYTHONPATH=. .venv/bin/python scripts/chatgpt-sync.py --no-voice-pass
PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py

# Gemini ou NotebookLM: as duas contas ativas
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py
PYTHONPATH=. .venv/bin/python scripts/gemini-parse.py
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py
PYTHONPATH=. .venv/bin/python scripts/notebooklm-parse.py

# Fonte CLI: sync ja inclui parse
PYTHONPATH=. .venv/bin/python scripts/codex-sync.py
```

Cada plataforma tem flags e requisitos proprios. Consulte seu `state.md`
antes de usar `--full`, `--dry-run`, `--account`, `--headed` ou flags de
assets. ChatGPT e Perplexity exigem janela visivel durante captura; as demais
fontes web usam o modo documentado no estado tecnico.

Depois de uma ou mais fontes web processadas:

```bash
PYTHONPATH=. .venv/bin/python scripts/unify-parquets.py
```

`data/unified/` e a saida cross-platform. A unificacao e idempotente e pode
ser refeita a partir de `processed`.

## Conferir uma rodada

```bash
cat data/raw/ChatGPT/LAST_CAPTURE.md
cat data/merged/ChatGPT/LAST_RECONCILE.md
PYTHONPATH=. .venv/bin/pytest
```

Nao considere uma fonte verde se o Parquet estiver anterior ao raw ou merged.
Discovery parcial, token expirado ou falha de asset exigem a acao definida no
`state.md`; nao apague dados para fazer os contadores parecerem consistentes.

## Relatorios Quarto

Renderize o perfil da fonte afetada depois de parse/unify:

```bash
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview.qmd
```

Os qmds compartilham `notebooks/_template.qmd`; a configuracao de cada fonte
permanece curta e as tabelas auxiliares sao renderizadas quando existirem.
Os HTMLs gerados ficam em `notebooks/_output/` e sao ignorados pelo Git.

Para servi-los localmente:

```bash
./scripts/serve-qmds.sh start
./scripts/serve-qmds.sh status
./scripts/serve-qmds.sh open
./scripts/serve-qmds.sh stop
```

## Dashboard e execucao sem interface

O dashboard executa quatro estagios: sync+parse, unify, Quarto e publish.
Falha em um estagio impede publicacao posterior; `dvc push` e `git push` so
ocorrem quando o operador marca Publish de forma deliberada.

```bash
# Pipeline sem Streamlit; exclui fontes que exigem janela visivel
PYTHONPATH=. .venv/bin/python scripts/headless-pipeline.py --no-publish
```

O historico e os locks de rodadas automatizadas ficam em `.runtime/`. Consulte
[dashboard.md](dashboard.md) para iniciar, verificar e diagnosticar a UI.

## Termos e recuperacao

- Termos de captura: [glossario de engenharia](../extractor-engineering/glossary.md).
- Recuperacao de coleta web: [web-collection.md](web-collection.md).
- Espaco, DVC e GC: [dvc-runbook.md](dvc-runbook.md).
