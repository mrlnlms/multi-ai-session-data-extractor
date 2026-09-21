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

Assets binarios imutaveis sao gravados no vault content-addressed. `raw` e
`merged` preservam JSON, manifests e demais evidencias independentes. Os
downloaders podem usar staging transitorio, mas uma captura vault bem-sucedida
remove esses bytes somente depois de verificar o blob commitado; Kimi e Qwen
tambem nao os projetam em `merged`.

## Transicao do asset vault

O contrato publicado em `assets.parquet`, `asset_links.parquet` e
`Message.asset_paths` nao determina onde os bytes ficam armazenados. O asset
vault central, content-addressed por SHA-256, esta materializado e validado em
`data/assets`; ele e o default operacional e foi publicado pelo DVC, com cache
local e remoto verificados em sincronia. Coletas incrementais reais ja
confirmaram o fluxo operacional. A auditoria preview-first classificou e
removeu de `raw` e `merged` apenas copias com bytes identicos comprovados no
vault; registros, manifests e snapshots em `external` foram preservados.

### Selecao explicita de leitura e escrita

Cada fonte usa um modo explicito, nunca inferido pela presenca de diretorios:

- `vault` e o default e usa o log duravel e os blobs em `data/assets`, com
  `data/` como raiz de dados; ambas as raizes podem ser sobrescritas
  explicitamente;
- `legacy` continua disponivel para compatibilidade e diagnostico de formatos
  antigos, mas nao representa uma segunda copia completa dos assets.

No dashboard, selecione `legacy` ou `vault` antes da execucao. No modo
headless, o default percorre as 13 fontes e a selecao de asset e por fonte;
fontes omitidas em `--asset-mode` usam `vault`:

```bash
PYTHONPATH=. .venv/bin/python -m src.workflows.headless --no-publish

# rollback temporario por fonte
PYTHONPATH=. .venv/bin/python -m src.workflows.headless --no-publish \
  --asset-mode Gemini=legacy
```

O modo `vault` escreve primeiro o blob imutavel e o registro de captura
append-only; `state.json`, as tabelas e os paths compativeis sao projecoes
reconstruiveis. O reader valida o blob antes de expor um path. Writers usam
lock exclusivo por fonte/conta, commits idempotentes e `fsync`; um append
interrompido e recuperado ate o ultimo commit completo. Aparicoes repetidas
precisam coincidir em todos os campos semanticos; `projection_order` e metadado
da materializacao e pode estar presente no backfill e ausente em capturas
incrementais sem criar uma segunda aparicao.

### Migracao, verificacao e restore local

A migracao excepcional e preview-first. Gere um plano fora de `data/`, revise
o JSON e execute-o em uma raiz temporaria. `run` valida o checksum e o drift
dos inputs, e recusa `data/assets` sem `--apply-canonical`:

```bash
PYTHONPATH=. .venv/bin/python -m src.operations.migrate_asset_vault plan \
  --data-root data --output /tmp/asset-vault-plan.json
PYTHONPATH=. .venv/bin/python -m src.operations.migrate_asset_vault run \
  /tmp/asset-vault-plan.json --vault-root /tmp/asset-vault/assets
PYTHONPATH=. .venv/bin/python -m src.operations.verify_asset_vault verify \
  --vault-root /tmp/asset-vault/assets
```

O restore local aceita somente um destino vazio, copia apenas o estado duravel
(`schema.json`, blobs e logs) e reconstrui os `state.json` antes de verificar:

```bash
PYTHONPATH=. .venv/bin/python -m src.operations.verify_asset_vault restore \
  --vault-root /tmp/asset-vault/assets \
  --destination /tmp/asset-vault-restored/assets
```

Esse comando prova reconstrução local. O vault publicado teve ponteiro, push e
sincronia do remoto verificados; um novo restore frio via Git/DVC fica reservado
como diagnostico de recuperacao, nao como gate automatico da publicacao.
Nenhum desses comandos apaga evidencia legacy.

### Retencao e rollback

No contrato atual, retenha juntos os blobs, `schema.json` e todos os
`scopes/*/*/records.jsonl`; os logs commitados sao a fonte duravel do estado do
vault. `state.json`, paths compativeis e Parquets podem ser reconstruidos. Nao
existe coleta de lixo autorizada para o vault e blobs nao devem ser removidos
isoladamente.

`processed` e `unified` permanecem no DVC. Um restore frio
do remoto e diagnostico opcional para divergencia ou incidente de recuperacao,
nao gate automatico de publicacao; os gates normais sao push bem-sucedido,
status local/remoto limpos e um novo recibo de archive assurance.

O modo `legacy` permanece para compatibilidade e diagnostico, mas nao constitui
mais uma segunda copia completa dos assets. O rollback integral dos bytes usa
uma revisao DVC anterior; a operacao normal e a recuperacao atual usam o vault.
O default `vault` nunca autoriza remover registros ou manifests legacy. A
limpeza dos bytes redundantes foi uma operacao separada, preview-first; `dvc
gc` continua sendo manutencao separada e exige aprovacao explicita.

O dry-run abaixo calcula SHA-256, confere cada copia contra o blob central e
grava a lista exata de candidatos, sem coletar, baixar ou excluir nada:

```bash
PYTHONPATH=. .venv/bin/python -m src.operations.audit_asset_retention \
  --data-root data --output .runtime/audits/asset-retention-audit.json
```

O comando e dry-run por padrao. Depois de revisar o relatorio, a limpeza
explicita reexecuta a auditoria e revalida cada hash antes da remocao:

```bash
PYTHONPATH=. .venv/bin/python -m src.operations.audit_asset_retention \
  --data-root data --apply \
  --output .runtime/audits/asset-retention-apply.json
```

No checkpoint aplicado, 24.056 copias (9.029.881.100 bytes logicos) foram
removidas sem bloqueios. Uma nova auditoria retornou zero candidatos.

Qualquer path sem blob identico aparece em `blocked` e nao e candidato. O
modo `--apply` recusa a operacao quando o dry-run fresco encontra qualquer
bloqueio e revalida tamanho, hash e identidade do arquivo imediatamente antes
de cada remocao.

Use `PYTHONPATH=. .venv/bin/python` para executar scripts sem depender do
Python global.

## Baseline de validacao entre sessoes

O registro local `.runtime/archive-assurance.json` guarda a ultima base
verificada/publicada: horario, commit Git e fingerprints dos ponteiros DVC e
do checkout de dados. Depois de um Publish completo, o pipeline o atualiza.
O hook de inicio de sessao do Codex mostra apenas uma linha; ele nao faz
consultas ao remoto nem carrega uma auditoria no contexto do agente.

```bash
# Leitura rapida, local e sem rede
PYTHONPATH=. .venv/bin/python -m src.operations.archive_assurance status

# Verificacao deliberada da base atual: frescor local, DVC, remoto e Git
PYTHONPATH=. .venv/bin/python -m src.operations.archive_assurance verify
```

`verify` atualiza o registro somente se todas as checagens concluirem. Um
registro ausente ou alterado indica que a nova base precisa ser validada; nao
significa que o remoto desapareceu. O fingerprint local detecta mudancas
posteriores sem recalcular hashes de conteudo nem cobrar requisicoes remotas
em toda abertura de chat. O DVC calcula/verifica conteudo na publicacao e na
verificacao deliberada.

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

# Gemini e NotebookLM: o workflow seleciona as contas e faz um parse ao final
PYTHONPATH=. .venv/bin/python -m src.workflows.headless --plats=Gemini,NotebookLM --no-publish

# Sync direto e excepcional sempre recebe uma conta; nao chama parse
PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.sync --account 1
PYTHONPATH=. .venv/bin/python -m src.platforms.notebooklm.commands.sync --account 1

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
