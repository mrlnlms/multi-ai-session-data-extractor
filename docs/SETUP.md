# Setup e retomada do projeto

Guia completo para instalar o projeto, recuperar um acervo existente e fazer
uma primeira coleta. Para uma visao geral, veja o [README.md](../README.md).

## O que cada camada guarda

| O que | Fonte de verdade | Como volta |
|---|---|---|
| Codigo, testes e documentacao publica | Git | `git clone` |
| Configuracao compartilhada do DVC (`.dvc/config`) | Git | vem no clone |
| Dados de sessoes (`data/`) | DVC | `dvc pull` |
| Cookies e perfis de browser (`.storage/`) | maquina atual | novo login quando necessario |
| Cache DVC, venv e HTMLs renderizados | maquina atual | recriar sob demanda |

O checkout e os dados nao devem ser sincronizados pelo Google Drive Desktop.
Os dados grandes pertencem ao DVC. Alguns detalhes pessoais do proprietario —
o workbench privado e o segredo OAuth local do DVC — ficam no complemento
privado, fora desta documentacao publica.

## Pre-requisitos

- **Python ≥3.12** (validado em 3.12 e 3.14)
- **macOS ou Linux** (Windows nao validado)
- **~5 GB de espaco livre** (varia com o volume de conversas)
- **Git** para clonar o repositorio

Confira a versao:

```bash
python3 --version
# Python 3.12.0 or higher
```

## 1. Clonar e instalar

```bash
git clone <repo-url>
cd multi-ai-session-data-extractor

# Criar ambiente virtual isolado
python3 -m venv .venv
source .venv/bin/activate

# Instalar o ambiente completo do projeto
pip install -r requirements.txt

# Instalar o Chromium usado pelo Playwright (~200 MB)
playwright install chromium
```

Daqui em diante, ao abrir um terminal novo:

```bash
source .venv/bin/activate
```

## 2. Recuperar um acervo existente

Se este nao e o primeiro uso do projeto, restaure antes os detalhes privados
do ambiente descritos em `private/SETUP-PRIVADO.md`. Em seguida, traga a base
canonico atual pelo DVC:

```bash
.venv/bin/dvc pull
.venv/bin/dvc status -c -r gdrive_remote
```

O primeiro comando pode abrir o fluxo OAuth no navegador. Os perfis em
`.storage/` nao fazem parte do DVC; para uma coleta nova, entre novamente nas
plataformas necessarias. Para apenas ler os dados recuperados ou abrir o
dashboard, nao e preciso fazer login nelas.

## 3. Login (uma vez por plataforma)

Cada plataforma web exige um login interativo inicial. O script abre um
navegador, voce entra manualmente e o perfil fica em
`.storage/<platform>-profile-<account>/` (ignorado pelo Git).

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.login
PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.login
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.login
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.login
PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.login
PYTHONPATH=. .venv/bin/python -m src.platforms.grok.commands.login
PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.login
```

Para uma conta adicional, crie primeiro a identidade no catalogo, escolha um
nome de profile apenas local, faca o login nesse profile e vincule-o ao UUID:

```bash
PYTHONPATH=. .venv/bin/python -m src.operations.accounts create --platform DeepSeek --display-name "Pessoal"
PYTHONPATH=. .venv/bin/python -m src.operations.accounts create --platform DeepSeek --display-name "Pessoal" --apply
PYTHONPATH=. .venv/bin/python -m src.platforms.deepseek.commands.login --account pessoal
PYTHONPATH=. .venv/bin/python -m src.operations.accounts bind ACCOUNT_ID --profile-key pessoal --apply
```

O nome `pessoal` identifica somente o profile nesta instalacao. A identidade
duravel e os paths raw/merged usam sempre `ACCOUNT_ID`.

**O que esperar:**

1. Uma janela Chromium abre na pagina de login.
2. Voce conclui email, senha, captcha ou 2FA diretamente na plataforma.
3. Ao chegar na pagina inicial, o script detecta o estado e normalmente fecha
   o navegador; tambem e seguro fecha-lo manualmente.
4. O perfil e preservado e os syncs seguintes nao pedem login ate a sessao
   expirar.

O Chrome pode oferecer "vincular", "ativar sincronizacao" ou criar um perfil
associado ao e-mail usado no login. Isso e **opcional** e nao faz parte da
configuracao do extrator. Recusar esse vinculo nao invalida o profile local,
nao significa logout da plataforma e nao deve impedir login, auth-check ou
coleta. O extrator depende somente da sessao da plataforma salva no diretorio
tecnico `.storage/<plataforma>-profile-<chave>/`.

Para evitar confusao em operacoes multi-conta, confira a identidade mostrada
pelo proprio servico antes de fechar a janela e vincule o profile local ao UUID
correto. Nunca use o avatar, e-mail ou estado de sync do Chrome como evidencia
de qual conta da plataforma esta autenticada.

**CLIs (Claude Code, Codex, Gemini CLI e Antigravity CLI):** o coletor nao
faz login. Ele copia dados dos diretorios locais da ferramenta, como
`~/.claude/projects/`, `~/.codex/sessions/` e `~/.gemini/tmp/`.

## 4. Primeira coleta

Comece por uma plataforma para validar o ambiente:

```bash
PYTHONPATH=. .venv/bin/python -m src.workflows.headless --plats=ChatGPT --no-publish
```

Para sincronizar uma conta web especifica, selecione sua identidade imutavel.
O preview nao altera dados; `--apply` executa sync + parse para a conta, sem
unify ou publicacao:

```bash
PYTHONPATH=. .venv/bin/python -m src.operations.accounts list
PYTHONPATH=. .venv/bin/python -m src.workflows.account_sync ACCOUNT_ID
PYTHONPATH=. .venv/bin/python -m src.workflows.account_sync ACCOUNT_ID --apply
```

O workflow seletivo chama o sync web da fonte, que faz captura, download de
assets e reconciliacao:

1. **Captura** — baixa pela API interna e salva em
   `data/raw/ChatGPT/account-<UUID>/`.
2. **Assets** — imagens, uploads, arquivos de projeto e equivalentes.
3. **Reconciliacao** — consolida com a captura anterior em
   `data/merged/ChatGPT/account-<UUID>/`. Conversas que sumiram do servidor ficam com
   `is_preserved_missing=True`.

Em seguida, o mesmo workflow roda o parser para converter o merged em Parquet
no schema canonico.

O dashboard e a pipeline automatizada fazem esse parser depois de cada sync
web bem-sucedido e antes da unificacao. Os syncs de CLI ja incluem o parser.

Repita nas outras plataformas e consolide o conjunto cross-platform:

```bash
PYTHONPATH=. .venv/bin/python -m src.workflows.unify
```

Isso materializa os Parquets unificados em `data/unified/`.

## 5. Multiplas contas (Gemini, NotebookLM)

Gemini e NotebookLM suportam qualquer quantidade de identidades catalogadas.
Cada UUID ativo aponta para um profile local por binding; o modo headless
seleciona todas as contas executaveis, enquanto `account_sync` seleciona uma:

```bash
PYTHONPATH=. .venv/bin/python -m src.workflows.headless --plats=Gemini,NotebookLM --no-publish
PYTHONPATH=. .venv/bin/python -m src.workflows.account_sync ACCOUNT_ID --apply
```

O NotebookLM tambem possui um arquivo corporativo historico, separado das
contas de login atuais. O parser oficial inclui esse snapshot quando ele esta
restaurado pelo DVC e falha com seguranca quando o diretorio esperado esta
ausente; `--without-historical` e uma exclusao deliberada, nao o padrao.

## 6. Problemas comuns

### Cookie expirado ou redirecionamento ao login

A sessao da plataforma expirou. Faca login de novo:

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.login
```

### ChatGPT abre uma janela mesmo durante o sync

E esperado: o Cloudflare bloqueia esses clientes sem janela. O mesmo ocorre
com Perplexity. O modo de navegacao usado pode variar por plataforma; consulte
o `state.md` correspondente quando estiver diagnosticando uma fonte.

### Queda de discovery ou sync abortado

O extractor protege contra capturas parciais. Quando a listagem inicial cai de
forma relevante frente ao maior historico conhecido, ele aborta antes de
gravar para nao contaminar `data/raw/` cumulativo.

Causas comuns:

- Unstable discovery endpoint (e.g. OpenAI's `/projects` occasionally
  returns 404)
- Cookie expired and fallback only partially resolves
- Server changed structure

O que fazer:

```bash
# Try again (transient instability usually resolves)
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.sync --account default

# Investigate manually
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.sync --account default --dry-run
```

### O sync esta demorando demais

A primeira captura e lenta porque baixa **tudo**. As seguintes sao
incrementais e costumam levar de segundos a minutos.

Tempos tipicos da primeira captura:

| Platform | Time |
|---|---|
| Claude.ai | 10-30 min |
| ChatGPT | 5-30 min (depends on volume) |
| NotebookLM | 30-90 min (large binaries — slide decks, audios) |
| Others | 1-10 min |

### `ModuleNotFoundError` ao rodar scripts

Voce esqueceu de ativar `.venv` ou nao esta na raiz do projeto:

```bash
source .venv/bin/activate
cd /path/to/multi-ai-session-data-extractor
PYTHONPATH=. .venv/bin/python -m src.platforms.<source_id>.commands.<action>
```

### Perplexity retorna HTTP 403 no sync

E o mesmo tipo de bloqueio do ChatGPT pelo Cloudflare. O sync ja usa uma
janela visivel nessa plataforma; se o erro persistir, recrie o perfil:

```bash
rm -rf .storage/perplexity-profile-default
PYTHONPATH=. .venv/bin/python -m src.platforms.perplexity.commands.login
```

### Quero recapturar tudo (sem aproveitar o incremental)

```bash
PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.sync --full
```

Isso busca todas as conversas de novo, nao apenas as alteradas. Ainda assim,
preserva o que ja esta em `data/raw/`.

### Quero apagar tudo e recomecar

```bash
# CAUTION: deletes raw + merged + processed (but .storage/ remains)
rm -rf data/raw data/merged data/processed data/unified
```

Cookies e perfis em `.storage/` nao sao apagados. Para remover tambem os
logins:

```bash
rm -rf data/ .storage/
```

Esses comandos apagam dados locais. Confirme antes que a base que voce quer
preservar esta publicada e recuperavel pelo DVC.

## DVC: cofre recuperavel da base atual

A pipeline regular grava em `data/raw/`, `data/merged/`, `data/assets/`,
`data/processed/` e `data/unified/`. `data/external/` preserva inputs manuais,
exports e snapshots excepcionais fora da aquisicao automatizada; operacoes e
adaptadores explicitos podem le-los ou cria-los sem transforma-los em captura
reproduzivel. Esses diretorios sao ignorados pelo Git e contem dados pessoais
que nao devem entrar no repositorio.

Este repositorio usa DVC como cofre recuperavel da **base canonica atual**. O
Git versiona o codigo e os ponteiros `.dvc`; o remoto guarda os dados grandes.
Isso nao promete recuperar para sempre cada snapshot historico: objetos DVC
antigos podem ser descartados deliberadamente depois que o estado atual for
publicado e verificado.

### Publicar uma coleta nova e validada

Depois de sync, parse e unify concluirem com sucesso, atualize os ponteiros de
dados e publique a base atual. E uma operacao deliberada: `dvc push` escreve
no armazenamento externo e `git push` publica os ponteiros. Use a sequencia de
validacao do runbook.

Guia operacional completo, incluindo limpeza de armazenamento:
[operations/dvc-runbook.md](operations/dvc-runbook.md).

## Proximos passos

- **Dashboard local** — `PYTHONPATH=. streamlit run dashboard/app.py`
- **Documentos descritivos por plataforma** —
  `quarto render notebooks/<plat>.qmd` (veja [operations/pipeline.md](operations/pipeline.md))
- **Analise de Parquet** — leia `data/unified/*.parquet` com pandas ou DuckDB
- **Limites conhecidos dos extractors** —
  [extractor-engineering/known-limitations.md](extractor-engineering/known-limitations.md)
