# DVC Runbook — cofre operacional da base atual

Este projeto e o pai/fonte canonica de captura: produz `raw`, `merged`,
Parquets processados e Parquets unificados. O Google Drive e o remoto DVC
operacional que guarda a **base canonica atual** quando ela nao cabe no Mac.
O projeto filho/consumidor `AI Interaction Analysis` le os Parquets publicados
daqui.

O DVC foi escolhido para armazenar muitos arquivos incrementais, deduplicados
e verificaveis sem transforma-los em um arquivo gigante. O historico Git dos
ponteiros existe, mas reter cada versao historica dos dados nao e um requisito
do produto: uma limpeza pode tornar revisoes antigas de dados irrecuperaveis.

## O que fica em cada lugar

| Camada | Conteudo | Contrato |
|---|---|---|
| Git | Codigo, documentacao e ponteiros `.dvc` | Historico do projeto e receita da base atual. |
| Google Drive / DVC | Objetos da base atual | Cofre recuperavel dos dados grandes. |
| `data/` | Checkout local dos dados | Descartavel depois de uma publicacao verificada. |
| `.dvc/cache/` | Cache local DVC | Descartavel e recriavel por `dvc pull`. |
| `private/` | Symlink para o workbench privado | Documentos e configuracoes duraveis fora do Git. |
| `.storage/` | Perfis de navegador e sessao | Estado local; exige novo login apos maquina limpa. |

Uma copia manual antiga do checkout no Drive nao e a fonte de verdade. O
remoto DVC e. O incidente que reconciliou uma dessas copias com o DVC esta em
[RECOVERY.md](RECOVERY.md) somente como registro historico concluido.

## Pastas rastreadas

| Pasta | Conteudo | Papel |
|---|---|---|
| `data/raw/` | Captura bruta e binarios | Evidencia primaria; downloaders preservam binarios existentes. |
| `data/merged/` | Reconciliacao cumulativa | Mantem registros `preserved_missing`. |
| `data/processed/` | Parquets canonicos por fonte | Interface de leitura para analises. |
| `data/unified/` | Parquets cross-platform | Contrato de dados para o consumidor. |
| `data/external/` | Inputs manuais e snapshots preservados | Evidencia ou entradas ativas fora da captura regular. |

O conteudo dessas pastas nao vai para Git diretamente: os arquivos `.dvc` sao
os ponteiros versionados. `data/external/README.md` continua documentacao
publica comum.

## Credenciais e setup

- O remoto e a pasta Google Drive `ai-interaction-source-dvc`.
- `.dvc/config` e compartilhada; `.dvc/config.local` contem o segredo OAuth e
  nao pode entrar no Git.
- O backup privado dessa configuracao e a instalacao em maquina nova ficam em
  `private/COMO-RETOMAR.md`.
- O cache de token do cliente DVC pode ser renovado por OAuth; ele nao e uma
  copia dos dados.

## Ciclo normal de atualizacao

Depois de uma coleta validada, o fluxo da fonte e:

```text
sync/copy -> reconcile -> parse -> unify -> dvc add -> commit -> dvc push -> git push
```

As fontes web executadas diretamente precisam de parse explicito; os syncs
das CLIs ja fazem copy + parse. O dashboard pode executar esse fluxo e o seu
estagio Publish publica o estado que o consumidor podera ler.

Antes de publicar uma mudanca de schema em `data/unified/`, coordenar o
contrato com `AI Interaction Analysis`.

```bash
# Conferir se working tree, cache e remoto estao coerentes
.venv/bin/dvc status
.venv/bin/dvc status --cloud

# Depois de sync + parse + unify, atualizar ponteiros DVC
.venv/bin/dvc add data/raw data/merged data/processed data/unified \
    data/external/manual-saves data/external/deep-research-md \
    data/external/perplexity-orphan-threads data/external/deepseek-snapshots \
    data/external/chatgpt-extension-snapshot data/external/claude-ai-snapshots \
    data/external/notebooklm-snapshots data/external/openai-gdpr-export \
    data/external/claude-code-config-snapshots \
    data/external/codex-config-snapshots \
    data/external/gemini-config-snapshots \
    data/external/grok-snapshots
git add data/*.dvc data/external/*.dvc data/.gitignore data/external/.gitignore
git commit -m "data: snapshot apos <operacao>"
.venv/bin/dvc push
git push
```

`dvc push` e `git push` sao escrita externa: um agente so os executa com
autorizacao explicita do usuario. Para o operador, fazem parte normal de uma
publicacao deliberada; marcar Publish no dashboard e uma autorizacao clara.

## Recuperar a base atual em outra maquina

O cenario suportado e apagar `data/` localmente para liberar espaco e, mais
tarde, reconstruir a base atual:

```bash
git clone <repositorio>
cd multi-ai-session-data-extractor
# criar/reparar o symlink private conforme private/COMO-RETOMAR.md
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/dvc pull
```

O primeiro `dvc pull` pode pedir OAuth. Perfis em `.storage/` nao sao parte
do restore: faca login novamente nas plataformas quando for coletar.

## Gerenciar espaco com DVC GC

`dvc gc` nao e parte da coleta. Ele e uma operacao deliberada de retencao que
remove do cache e, com `--cloud`, do Drive os objetos que nao devem mais ser
mantidos. Este projeto retem a base canonica atual, nao todas as versoes dos
dados apontadas pelo historico Git.

Antes de uma limpeza:

1. concluir e validar a coleta atual;
2. fazer `dvc add`, commit, `dvc push` e `git push` desse estado;
3. confirmar `dvc status --cloud` sem diferencas relevantes;
4. rodar a simulacao e revisar seu resultado com o proprietario.

```bash
# Protege o estado atual do worktree e mostra o que seria removido localmente
# e no Drive. Nao use --all-commits: ele preservaria o historico que este
# projeto deliberadamente nao retem.
.venv/bin/dvc gc --workspace --cloud --dry
```

Somente com aprovacao explicita, repetir o comando sem `--dry`. O DVC pedira
confirmacao interativa. Nunca use `--force` por conveniencia.

**Impacto assumido:** depois disso, `git checkout <commit-antigo>` pode
continuar mostrando o codigo e os ponteiros antigos, mas `dvc pull` daquele
estado pode falhar porque seus blobs foram descartados. A base atual e o
consumidor que a le continuam preservados.

## Problemas comuns

### Token expirou

Reautentique pelo fluxo descrito em `private/COMO-RETOMAR.md`; nao registre
segredos, token ou o conteudo de `.dvc/config.local` em Git.

### `data/` ou cache local sumiu

```bash
.venv/bin/dvc pull
```

Isso restaura a base canonica atual do Drive. Nao limpe ou reescreva dados
locais apenas para fazer o DVC “bater”; investigue primeiro `dvc status`.

## Limites com o projeto consumidor

Os cofres DVC sao separados. Uma limpeza neste remoto nao remove blobs do
remoto usado pelo `AI Interaction Analysis`; ela apenas pode retirar a
capacidade de restaurar revisoes antigas **desta** fonte. O consumidor deve
atualizar para uma revisao publicada atual quando precisar de dados novos.

Alternativas ao Google Drive podem ser pesquisadas no futuro para evitar a
poluicao visual de objetos hashados, mas nao ha migracao ativa. Ate que uma
alternativa seja comprovadamente viavel, o Drive e o remoto operacional.
