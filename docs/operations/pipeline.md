# Pipeline operations

Comandos cotidianos para capturar, processar e materializar os dados. O
[mapa de comandos](commands.md) tambem registra operacoes menos frequentes,
como manual saves e snapshots de configuracao. Para
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

Uma conta web ativa e vinculada localmente pode ser selecionada pelo UUID
imutavel. `python -m src.workflows.account_sync ACCOUNT_ID` mostra um preview;
`--apply` executa somente sync + parse da plataforma, sem unify, DVC ou Git.

## Atualizar uma fonte

Quando chamados diretamente, os nove syncs web executam captura, assets quando
aplicavel e reconcile; o parse correspondente deve vir depois. O dashboard e
o modo headless executam esse parse automaticamente após um sync web
bem-sucedido. Os quatro syncs de CLI ja fazem copy e parse.

```bash
# Fonte web: exemplo ChatGPT
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.sync --no-voice-pass
# Outra conta ChatGPT, depois de executar python -m src.platforms.chatgpt.commands.login --profile account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.sync --account account-2 --no-voice-pass
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.parse

# Outra conta Claude.ai, depois de executar python -m src.platforms.claude_ai.commands.login --profile account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.sync --profile account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.parse

# Outra conta Kimi, depois de executar python -m src.platforms.kimi.commands.login --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.parse

# Outra conta DeepSeek, depois de executar python -m src.platforms.deepseek.commands.login --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.parse

# Outra conta Qwen, depois de executar python -m src.platforms.qwen.commands.login --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.parse

# Outra conta Grok ou Perplexity, depois do login no perfil separado
PYTHONPATH=. .venv/bin/python -m src.platforms.grok.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.grok.commands.parse
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.sync --account account-2
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.parse

# Gemini e NotebookLM: tres contas ativas
PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.sync
PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.parse
PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.sync
PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.parse

# Fonte CLI: sync ja inclui parse
PYTHONPATH=. .venv/bin/python -m src.platforms.codex.commands.sync

# Antigravity CLI: recuperacao legacy e excepcional; sidecars passam a ser
# consumidos pelos parses seguintes
PYTHONPATH=. .venv/bin/python -m src.platforms.antigravity_cli.commands.recover_legacy --all-opaque
PYTHONPATH=. .venv/bin/python -m src.platforms.antigravity_cli.commands.parse
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
conta. O formato e `plataforma -> profile -> e-mail`; inclua apenas os profiles
que existem na maquina:

```json
{
  "chatgpt": {
    "default": "name@example.com"
  },
  "gemini": {
    "account-1": "name@example.com",
    "account-2": "other@example.com"
  }
}
```

O parser preserva esse e-mail na coluna legada `account`; se o arquivo ou o
mapeamento nao existir, o rótulo continua nulo. Separadamente, ele resolve o
UUID imutável `account_id` por plataforma e chave técnica no catálogo DVC. A
resolução falha antes de publicar a saída se uma conta web não estiver no
catálogo. IDs históricos de conversa não mudam. Por conter dados pessoais, o
arquivo real de rótulos permanece em `.storage/` e nunca entra no Git.

Na unificação, as chaves começam por `(source, account_id, ...)`. Parquets
legados sem a coluna são aceitos como nulos; nenhum UUID é inferido de e-mail.
Fontes CLI e importações manuais permanecem nulas até exporem identidade
durável.

Depois de uma ou mais fontes web processadas:

```bash
PYTHONPATH=. .venv/bin/python -m src.workflows.unify
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
PYTHONPATH=. .venv/bin/python -m src.workflows.serve_reports start
PYTHONPATH=. .venv/bin/python -m src.workflows.serve_reports status
PYTHONPATH=. .venv/bin/python -m src.workflows.serve_reports open
PYTHONPATH=. .venv/bin/python -m src.workflows.serve_reports stop
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
PYTHONPATH=. .venv/bin/python -m src.workflows.headless --no-publish
```

O historico e os locks de rodadas automatizadas ficam em `.runtime/`. Consulte
[dashboard.md](dashboard.md) para iniciar, verificar e diagnosticar a UI.

## Termos e recuperacao

- Termos de captura: [glossario de engenharia](../extractor-engineering/glossary.md).
- Recuperacao de coleta web: [web-collection.md](web-collection.md).
- Espaco, DVC e GC: [dvc-runbook.md](dvc-runbook.md).
