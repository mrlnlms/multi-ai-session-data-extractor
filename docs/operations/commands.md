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
python -m src.workflows.account_sync ACCOUNT_ID --apply
python -m src.platforms.codex.commands.sync
```

As flags, requisitos de browser e particularidades de cada fonte ficam em
`docs/extractor-engineering/platforms/<web|cli>/<source>/state.md`.

O inventario tecnico de contas e lido por `src/accounts.py` a partir dos
defaults compativeis, do registro privado, dos profiles e das arvores
raw/merged preservadas. Essas evidencias nao validam autenticacao. O workflow
compartilhado seleciona, em ordem, contas ativas ou ainda nao catalogadas,
exclui `disabled`, `historical` e archives, executa cada sync web com a conta
explicita e roda o parser consolidado uma vez ao final.

## Workflows transversais

| Finalidade | Comando | Quando usar |
|---|---|---|
| Pipeline sem Streamlit | `python -m src.workflows.headless --no-publish` | Rodada automatizada; sem `--no-publish`, publica via DVC e Git |
| Unificar Parquets | `python -m src.workflows.unify` | Depois que os Parquets por fonte estiverem atuais |
| Importar saves manuais | `python -m src.workflows.manual_saves` | Quando houver clippings, copy/paste ou renders de terminal em `data/external/manual-saves/` |
| Servir relatorios | `python -m src.workflows.serve_reports open` | Depois de renderizar os HTMLs Quarto |
| Snapshot de configuracoes CLI | `python -m src.capture.cli.snapshot` | Preservar versoes sanitizadas de skills, hooks e configuracoes locais |
| Sync de uma conta | `python -m src.workflows.account_sync ACCOUNT_ID` | Preview por UUID; `--apply` executa sync + parse, sem unify/publicacao |
| Validar cobertura de arquivos | `python -m src.operations.asset_coverage_audit --check` | Gate pre-publicacao independente para as 9 fontes web e as 4 CLIs; retorno diferente de zero indica gap |
| Auditar copias redundantes | `python -m src.operations.audit_asset_retention --output .runtime/audits/asset-retention-audit.json` | Dry-run local: lista apenas paths raw/merged cujos bytes foram comprovados no vault |
| Remover copias redundantes | `python -m src.operations.audit_asset_retention --apply --output .runtime/audits/asset-retention-apply.json` | Reaudita tudo e remove somente arquivos raw/merged novamente comprovados no vault; aborta se a auditoria inicial tiver bloqueios |

## Operacoes de conta

`python -m src.operations.accounts` lista, cria, altera lifecycle, vincula um
profile local e executa uma verificacao explicita de login. Criacao, lifecycle
e binding apenas mostram preview sem `--apply`; nenhuma operacao exclui a
identidade ou dados preservados. `auth-check` nunca e executado na abertura do
dashboard e so persiste sua observacao quando recebe `--apply`.
Depois de conferir uma sessao em navegador visivel, o operador pode registrar
essa evidencia local sem consultar a plataforma:

```bash
python -m src.operations.accounts auth-confirm ACCOUNT_ID
python -m src.operations.accounts auth-confirm ACCOUNT_ID --apply
```

O primeiro comando e apenas preview. O segundo registra status `valid`, horario
e metodo `operator`; nao executa login, sync, DVC ou Git.
Essa confirmacao se refere a conta exibida pela plataforma, nunca a uma conta
vinculada ao Chrome. Login/sincronizacao do provedor do navegador e opcional e
nao entra no inventario nem na avaliacao de autenticacao.
Um sync seletivo concluido com sucesso tambem atualiza a observacao local para
`valid` com metodo `sync`.

As acoes expostas pela interface e por esses servicos significam:

| Acao | Efeito |
|---|---|
| `lifecycle` | Altera explicitamente a conta entre `active`, `disabled` e `historical`, sem apagar identidade ou dados. |
| `bind` | Associa o UUID da conta ao profile de navegador local que contem sua sessao autenticada. |
| `auth-check` | Faz uma leitura minima na plataforma e registra localmente o resultado observado. |
| `auth-confirm` | Registra a confirmacao manual de que o operador viu a conta autenticada no navegador. |
| `sync` | Executa captura e parse seletivos para a conta identificada pelo UUID; nao executa unify nem publicacao. |
| `login` | Abre o fluxo headed especifico da plataforma; senha e MFA sao fornecidos diretamente pelo usuario ao servico. |

`account_id` e a unica identidade imutavel. `profile_key` identifica somente o
profile local apontado pelo binding dessa instalacao. O catalogo v2 e a
dimensao analitica nao possuem `technical_key`; o leitor v1 existe apenas na
fronteira da migracao dos paths antigos. O glossario e a justificativa completa
ficam em
[`account-architecture.md`](../product/account-architecture.md#31-glossario-de-conta).

Manual saves nao substituem a captura oficial. Eles geram arquivos
`<source>_manual_<table>.parquet` na pasta processada da plataforma e sao
incluidos pela unificacao. Consulte `src/importers/manual/` para os formatos
aceitos.

## Operacoes excepcionais

### Migracao da identidade e dos paths de contas

O migrador preserva os UUIDs do catalogo v1, planeja a passagem de raw, merged
e snapshots historicos aplicaveis para `account-<UUID>` e grava o catalogo v2
por ultimo. O padrao e apenas preview; ele nao executa DVC, Git ou publicacao:

```bash
python -m src.operations.migrate_account_identity
python -m src.operations.migrate_account_identity --apply
```

`--apply` altera dados canonicos e exige uma rodada operacional deliberada. A
migracao local foi aplicada em 2026-09-21; o comando permanece documentado para
restauracoes ou checkouts que ainda contenham o catalogo v1.

### Adocao do catalogo de contas

O catalogo arquivavel de identidade e lifecycle pode ser proposto a partir do
inventario local sem alterar dados. Por padrao, a operacao imprime o JSON
completo; contas fora dos defaults operacionais e archives historicos exigem
classificacao explicita. `--write` grava somente o path indicado, de forma
atomica, e nunca chama Git ou DVC:

```bash
python -m src.operations.bootstrap_account_catalog \
  --classify Qwen:retired=historical \
  --captured-at 2026-09-13T00:00:00Z
```

O catalogo nao inclui rotulos privados, profiles ou estado de autenticacao.
Materializar `data/accounts/catalog.json` e executar `dvc add` sao passos
separados, sujeitos a revisao e autorizacao explicita.

### Manutencao DVC

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
