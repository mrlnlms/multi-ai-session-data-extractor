# Pipeline operations

Comandos cotidianos para capturar, processar e materializar os dados. Para
instalacao e login, use [SETUP.md](../SETUP.md). Para uma rodada web segura,
use [web-collection.md](web-collection.md). Regras de DVC e publicacao ficam
em [dvc-runbook.md](dvc-runbook.md).

```text
sync/copy -> raw -> reconcile -> parse -> processed -> unify -> unified
```

Os reconcilers tratam assets binarios como imutaveis: ao preserva-los em
`merged`, tentam criar hardlinks para evitar uma segunda copia fisica e usam
uma copia normal como fallback quando o filesystem nao suporta links. JSON,
manifestos e outros arquivos que podem ser anotados continuam independentes.

Use `PYTHONPATH=. .venv/bin/python` para executar scripts sem depender do
Python global.

## Atualizar uma fonte

Quando chamados diretamente, os nove syncs web executam captura, assets quando
aplicavel e reconcile; o parse correspondente deve vir depois. O dashboard e
o modo headless executam esse parse automaticamente após um sync web
bem-sucedido. Os quatro syncs de CLI ja fazem copy e parse.

```bash
# Fonte web: exemplo ChatGPT
PYTHONPATH=. .venv/bin/python scripts/platform/chatgpt/sync.py --no-voice-pass
# Outra conta ChatGPT, depois de executar scripts/platform/chatgpt/login.py --profile account-2
PYTHONPATH=. .venv/bin/python scripts/platform/chatgpt/sync.py --account account-2 --no-voice-pass
PYTHONPATH=. .venv/bin/python scripts/platform/chatgpt/parse.py

# Outra conta Claude.ai, depois de executar scripts/platform/claude/login.py --profile account-2
PYTHONPATH=. .venv/bin/python scripts/platform/claude/sync.py --profile account-2
PYTHONPATH=. .venv/bin/python scripts/platform/claude/parse.py

# Outra conta Kimi, depois de executar scripts/platform/kimi/login.py --account account-2
PYTHONPATH=. .venv/bin/python scripts/platform/kimi/sync.py --account account-2
PYTHONPATH=. .venv/bin/python scripts/platform/kimi/parse.py

# Outra conta DeepSeek, depois de executar scripts/platform/deepseek/login.py --account account-2
PYTHONPATH=. .venv/bin/python scripts/platform/deepseek/sync.py --account account-2
PYTHONPATH=. .venv/bin/python scripts/platform/deepseek/parse.py

# Outra conta Qwen, depois de executar scripts/platform/qwen/login.py --account account-2
PYTHONPATH=. .venv/bin/python scripts/platform/qwen/sync.py --account account-2
PYTHONPATH=. .venv/bin/python scripts/platform/qwen/parse.py

# Outra conta Grok ou Perplexity, depois do login no perfil separado
PYTHONPATH=. .venv/bin/python scripts/platform/grok/sync.py --account account-2
PYTHONPATH=. .venv/bin/python scripts/platform/grok/parse.py
PYTHONPATH=. .venv/bin/python scripts/platform/perplexity/sync.py --account account-2
PYTHONPATH=. .venv/bin/python scripts/platform/perplexity/parse.py

# Gemini e NotebookLM: tres contas ativas
PYTHONPATH=. .venv/bin/python scripts/platform/gemini/sync.py
PYTHONPATH=. .venv/bin/python scripts/platform/gemini/parse.py
PYTHONPATH=. .venv/bin/python scripts/platform/notebooklm/sync.py
PYTHONPATH=. .venv/bin/python scripts/platform/notebooklm/parse.py

# Fonte CLI: sync ja inclui parse
PYTHONPATH=. .venv/bin/python scripts/platform/codex/sync.py

# Antigravity CLI: recuperacao legacy e excepcional; sidecars passam a ser
# consumidos pelos parses seguintes
PYTHONPATH=. .venv/bin/python scripts/platform/antigravity-cli/recover-legacy.py --all-opaque
PYTHONPATH=. .venv/bin/python scripts/platform/antigravity-cli/parse.py
```

O parse oficial do NotebookLM tambem inclui todos os snapshots historicos em
`data/external/notebooklm-snapshots/`. Se esse diretorio DVC esperado nao
estiver restaurado, o comando falha antes de regravar `processed/`, evitando
que uma reconstrucao parcial apague o arquivo historico silenciosamente. Use
`--without-historical` somente quando quiser deliberadamente uma saida com as
contas atuais.

Perder acesso a uma conta nao apaga seu acervo capturado. Para contas no
formato atual, preserve os respectivos `raw/` e `merged/` e pare de sincronizar
o profile inacessivel; o parser continua lendo sua arvore cumulativa. Snapshots
de formatos antigos ficam imutaveis em `data/external/` e entram por um
adaptador da propria plataforma. Nenhum desses mecanismos recupera registros
que nunca foram capturados antes da perda de acesso.

Cada plataforma tem flags e requisitos proprios. Consulte seu `state.md`
antes de usar `--full`, `--dry-run`, `--account`, `--headed` ou flags de
assets. ChatGPT e Perplexity exigem janela visivel durante captura; as demais
fontes web usam o modo documentado no estado tecnico.

## Proveniencia de conta web

Os parsers web leem opcionalmente `.storage/accounts.json`, um arquivo local
ignorado pelo Git que associa uma plataforma e um profile tecnico ao e-mail da
conta. Copie `config/accounts.example.json`, preencha apenas os profiles que
existem na maquina e mantenha o arquivo em `.storage/`. O parser grava esse
e-mail na coluna canonica `account`; se nao houver mapeamento, o valor continua
nulo. Os IDs historicos de conversa nao mudam por causa dessa etiquetagem.

Depois de uma ou mais fontes web processadas:

```bash
PYTHONPATH=. .venv/bin/python scripts/workflows/unify-parquets.py
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
Esse diretorio e a fonte unica dos renders: o dashboard aponta para o servidor
local abaixo e nao copia nem cria symlinks dos relatorios em `static/`.

Para servi-los localmente:

```bash
./scripts/workflows/serve-qmds.sh start
./scripts/workflows/serve-qmds.sh status
./scripts/workflows/serve-qmds.sh open
./scripts/workflows/serve-qmds.sh stop
```

Por padrao, os links do dashboard usam `http://localhost:8765`. Se o servidor
for executado com outra porta, configure tambem a base usada pelo dashboard,
por exemplo `PORT=8766 QMD_REPORT_BASE_URL=http://localhost:8766`.

Os HTMLs derivados da base real podem conter informacao sensivel. Uma eventual
publicacao via GitHub Pages deve usar uma build separada com dados sinteticos,
nunca `notebooks/_output/`.

## Dashboard e execucao sem interface

O dashboard executa quatro estagios: sync+parse, unify, Quarto e publish.
Falha em um estagio impede publicacao posterior; `dvc push` e `git push` so
ocorrem quando o operador marca Publish de forma deliberada.

```bash
# Pipeline sem Streamlit; exclui fontes que exigem janela visivel
PYTHONPATH=. .venv/bin/python scripts/workflows/headless-pipeline.py --no-publish
```

O historico e os locks de rodadas automatizadas ficam em `.runtime/`. Consulte
[dashboard.md](dashboard.md) para iniciar, verificar e diagnosticar a UI.

## Termos e recuperacao

- Termos de captura: [glossario de engenharia](../extractor-engineering/glossary.md).
- Recuperacao de coleta web: [web-collection.md](web-collection.md).
- Espaco, DVC e GC: [dvc-runbook.md](dvc-runbook.md).
