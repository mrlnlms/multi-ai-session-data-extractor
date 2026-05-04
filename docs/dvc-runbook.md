# DVC Runbook — Cofre completo dos dados em Google Drive

Guia operacional do DVC neste projeto. **Este projeto eh o cofre canonico
da pipeline de captura** (raw → merged → processed → unified + external).
Versionamento via DVC permite restore total mesmo apos deletar tudo nas
plataformas + apagar `data/` localmente.

## O que o DVC faz aqui

- Versiona pastas grandes (`data/raw/`, `data/merged/`, `data/processed/`,
  `data/unified/`, `data/external/<subdirs>`) como "git pra dados".
- Arquivos reais ficam no Google Drive (pasta `ai-interaction-dvc`,
  compartilhada com o projeto pai `~/Desktop/AI Interaction Analysis/`).
- No git ficam so os ponteiros `.dvc` (arquivos pequenos com hash MD5).
- Cada commit do git captura o estado dos dados naquele momento — `git
  checkout` + `dvc checkout` volta no tempo.
- Modo **content-addressed**: nunca sobrescreve, nunca apaga. Deleções no
  local nao propagam pro Drive.

## Pastas trackeadas

| Pasta | Conteudo | Por que track |
|---|---|---|
| `data/raw/` | Saida bruta dos extractors (JSON + binarios) | Recover apos deletar plataforma; principio "capturar uma vez" |
| `data/merged/` | Saida dos reconcilers (JSON cumulativo + preserved_missing) | Recover sem precisar re-rodar reconcile pesado |
| `data/processed/` | Parquets canonicos per-source | Interface read-only pro consumer (pai) via `dvc import-url` |
| `data/unified/` | Parquets cross-platform (UNION ALL via DuckDB) | Idem, mais 4 qmds cross-plat consumindo |
| `data/external/manual-saves/` | Inputs pros parsers manuais (clippings_obsidian, copypaste_web, terminal_cc) | Inputs ativos do pipeline |
| `data/external/<demais subdirs>` | Snapshots UI + GDPR exports + thread orphans | Preservacao historica fora do pipeline |

`data/external/README.md` continua git-tracked normalmente — ele documenta
as subpastas, nao eh dado pessoal.

## Credenciais (compartilhadas com o projeto pai)

- **Remote:** Google Drive, pasta `ai-interaction-dvc` (ID: `101HMnOKvRYPZ6qQQu9iqCDcyWr_qx8fo`)
- **Autenticacao:** OAuth Client em `console.cloud.google.com` (projeto `ai-interaction-dvc`)
- **Client ID:** no `.dvc/config` (commitado no git — nao eh secreto)
- **Client Secret:** no `.dvc/config.local` (gitignored — nao commitado)
- **Token cacheado em:** `~/Library/Caches/pydrive2fs/` (compartilhado entre
  filho e pai; renovavel automaticamente, expira a cada ~6 meses)

## Comandos do dia-a-dia

Pre-requisito: `.venv` ativado ou usar `.venv/bin/dvc` direto.

### Apos rodar extractor / reconciler / parser

```bash
# Captura mudancas (rapido — DVC usa cache de hash por inode+mtime)
.venv/bin/dvc add data/raw data/merged data/processed data/unified \
    data/external/manual-saves data/external/deep-research-md \
    data/external/perplexity-orphan-threads data/external/deepseek-snapshots \
    data/external/chatgpt-extension-snapshot data/external/claude-ai-snapshots \
    data/external/notebooklm-snapshots data/external/openai-gdpr-export

# Commit dos ponteiros via script obrigatorio do projeto
git add data/*.dvc data/external/*.dvc data/.gitignore data/external/.gitignore
~/.claude/scripts/commit.sh "data: snapshot apos <operacao>"

# Upload dos deltas pro Drive (so blobs novos sobem; content-addressed)
.venv/bin/dvc push
```

### Conferir estado

```bash
.venv/bin/dvc status              # local vs cache
.venv/bin/dvc status --cloud      # local vs remote
.venv/bin/dvc remote list
```

### Recover total (cenario primario do cofre)

Cenario: deletei tudo nas plataformas + apaguei `data/` localmente. Quero
voltar ao estado de qualquer commit.

```bash
# Volta o ponteiro git pro commit desejado (ou main pro estado atual)
git checkout main

# DVC restaura todas as pastas a partir do remote
.venv/bin/dvc pull
```

Primeira pull em maquina nova abre browser pra OAuth (mesma conta gmail).

### Voltar no tempo (snapshot historico)

```bash
git log -- data/raw.dvc                # commits que mexeram em raw
git checkout <commit-hash>             # volta o ponteiro
.venv/bin/dvc checkout                 # DVC monta data/raw daquele commit
```

Voltar pro presente:
```bash
git checkout main && .venv/bin/dvc checkout
```

### Garbage collection (NAO RODAR sem necessidade)

Pelo principio "capturar uma vez, nunca rebaixar", **nao rode `dvc gc` por
default** — historico das capturas eh precious. Se algum dia o Drive
estourar:

```bash
# Ver o que seria apagado, sem apagar
.venv/bin/dvc gc --cloud --all-branches --all-tags --all-commits --dry-run
```

E **muito** importante: rodar com `--all-branches --all-tags --all-commits`
pra preservar historico. Sem essas flags, gc apaga tudo que nao eh
referenciado pelos ponteiros do commit atual. Repos do filho e do pai
compartilham o mesmo remote — gc roda no contexto de **um repo so**, nao
conhece os ponteiros do outro. Cuidado redobrado.

## Situacoes problematicas

### Token expirou (`invalid_grant: Token has been expired or revoked`)

```bash
rm -rf ~/Library/Caches/pydrive2fs/
.venv/bin/dvc push   # ou pull — abre browser pra reautenticar
```

Mesma conta gmail. Renova token automaticamente. Vale tambem pro pai (cache
compartilhado).

### "Apaguei data/<algo> sem querer"

```bash
.venv/bin/dvc checkout   # restaura tudo a partir do cache local
# se cache local tambem foi embora:
.venv/bin/dvc pull       # baixa do Drive
```

### "dvc push falhou com erro 403"

1. Token expirou → veja item acima
2. Email saiu da test users list: https://console.cloud.google.com/auth/audience?project=ai-interaction-dvc
3. Pasta `ai-interaction-dvc` no Drive mudou de owner ou foi deletada

### "Quero migrar pra outra Google Account"

```bash
# Desautoriza OAuth na conta antiga: https://myaccount.google.com/permissions
rm -rf ~/Library/Caches/pydrive2fs/
.venv/bin/dvc push   # OAuth com a nova conta
```

## Arquivos importantes

| Arquivo | Vai pro git? | Por que |
|---|---|---|
| `.dvc/config` | SIM | Config compartilhada — URL do remote, client_id |
| `.dvc/config.local` | NAO (gitignored) | Contem `gdrive_client_secret` |
| `.dvc/cache/` | NAO (gitignored) | Cache local dos blobs |
| `.dvcignore` | SIM | Padroes que DVC ignora |
| `data/*.dvc` | SIM | Ponteiros (hash + size + paths) |
| `data/external/*.dvc` | SIM | Idem, granular por subpasta |
| `data/.gitignore` + `data/external/.gitignore` | SIM | Geram pelo DVC, dizem pro git ignorar pastas trackadas |
| Conteudo de `data/raw/`, `data/merged/`, etc | NAO | Versionado via DVC |

## Co-existencia com o projeto pai

Filho e pai compartilham o **mesmo remote gdrive** (`101HMno...`). Como DVC
eh content-addressed:

- Blobs identicos (ex: parquets canonicos que o pai gerou no passado e que
  batem com hash do filho atual) **nao sao re-uploadados** — DVC pula.
- Blobs diferentes coexistem no mesmo bucket sem conflito.
- `.dvc` files de cada projeto ficam em repos git distintos, sem se
  misturar.

**Cuidado com `dvc gc`:** rodar no pai pode apagar blobs que so o filho
referencia, e vice-versa. Por isso a recomendacao de **nao rodar gc**
casualmente.

O pai consome os canonicos do filho via `dvc import-url`:

```bash
# No pai
dvc import-url <url-do-filho-no-github> data/processed/ -o data/canonical/
dvc import-url <url-do-filho-no-github> data/unified/ -o data/canonical-unified/
```

(Comando exato sera firmado quando a migracao do pai for executada.)

## Quando NAO usar DVC

- Anotacoes temporarias → `local/` (gitignored)
- HTML rendirizado pelo Quarto → `notebooks/_output/` (gitignored)
- Logs → fora de `data/`

## Referencias

- Docs DVC: https://dvc.org/doc
- Pasta Drive: https://drive.google.com/drive/folders/101HMnOKvRYPZ6qQQu9iqCDcyWr_qx8fo
- Projeto Google Cloud: `ai-interaction-dvc`
- Runbook do pai (referencia historica): `~/Desktop/AI Interaction Analysis/docs/dvc-runbook.md`
