# Glossario — engenharia de extractors

Termos de captura, reconciliacao e parser. Para DVC, publicacao e retencao,
veja o [glossario operacional](../operations/glossary.md).

## Discovery, merged e baseline

| Termo | Significado |
|---|---|
| **Discovery** | Snapshot do que o servidor lista agora. Pode subir com conversas novas e cair por exclusao, expiracao ou falha upstream; nao e a nossa fonte de verdade. |
| **Merged** | Catalogo cumulativo local de tudo que ja foi observado. Nao deve diminuir: registros que somem do servidor permanecem marcados como `preserved_missing`. |
| **Baseline** | Maior valor de discovery registrado nos logs. E uma medida de seguranca para detectar uma listagem parcial antes que ela contamine o raw. |

O guardrail fail-fast compara a discovery atual com o baseline. Uma queda acima
do limite configurado aborta antes de gravar uma captura potencialmente
corrompida. O baseline pode ser refeito sem perder o acervo; o merged nao.

> Discovery pode cair. Merged nao pode.

## Captura e preservacao

### Raw

Captura direta do servidor em `data/raw/<Source>/`, com JSON, binarios e logs.
E atualizada a cada execucao e ainda nao recebeu as regras cumulativas de
preservacao.

### Reconcile

Etapa que combina o raw atual com o merged anterior. Ela adiciona registros
novos, atualiza os alterados, copia os inalterados e preserva os ausentes do
servidor. O resultado se torna o novo merged.

| Estado | Significado |
|---|---|
| `added` | Existe no raw atual, mas nao no merged anterior. |
| `updated` | Existe nos dois e mudou (por exemplo, `update_time` ou enriquecimento). |
| `copied` | Existe nos dois e nao mudou. |
| `preserved_missing` | Existia antes e desapareceu da listagem atual; fica preservado localmente. |

### `preserved_missing` / `last_seen_in_server`

Indica que um registro conhecido nao apareceu na observacao atual do servidor.
Nao significa que a conversa foi apagada localmente: ela continua no merged e
nos Parquets, permitindo ao consumidor distinguir o acervo preservado do que
ainda esta observavel upstream.

### Incremental e `--full`

**Incremental** busca so o que mudou desde a ultima captura, normalmente por
`update_time`; e o caminho rotineiro. **`--full`** refaz a busca de tudo e e
reservado para diagnostico ou para uma nova base de captura. Nenhum dos dois
autoriza apagar o historico local.

### Hardlink

Dois caminhos para o mesmo arquivo fisico. E usado quando capturas distintas
referenciam o mesmo binario; nao duplica espaco. O arquivo so desaparece ao
remover seu ultimo link.

### Asset vault

Armazenamento central append-only para assets, com blobs imutaveis enderecados
por SHA-256 e logs duraveis por fonte/conta. `state.json`, paths compativeis e
tabelas publicadas sao projecoes reconstruiveis desses logs e blobs. O vault
esta materializado em `data/assets` e e o default operacional, mas ainda nao foi
staged ou publicado pelo DVC; `legacy` permanece como rollback explicito e suas
arvores devem ser preservadas. O
[procedimento operacional](../operations/pipeline.md#transicao-do-asset-vault)
documenta selecao, restore, retencao e rollback.

### Modo de asset (`legacy` / `vault`)

Selecao explicita da fronteira de armazenamento usada por uma fonte.
`legacy` le e grava as arvores atuais; `vault` usa por default `data/assets` e
`data`, aceita overrides explícitos e opera sobre os logs/blobs centrais. O modo
nunca deve ser inferido pela existencia de arquivos. Essa escolha altera o
armazenamento e o reader, nao o schema publicado de `Asset` e `AssetLink`.

### Voice pass

Etapa opcional que abre uma conversa no DOM para procurar a transcricao de
uma mensagem de voz que nao veio pela API. E lenta e pode ser pulada com
`--no-voice-pass` quando a cobertura existente for suficiente.

### Multi-account

Uma fonte com mais de uma conta capturada pelo mesmo projeto. Gemini e
NotebookLM usam diretorios por conta e o campo canonico `Conversation.account`;
o identificador da conversa recebe namespace da conta para impedir colisoes.
O sync pode percorrer todas as contas ou receber `--account N`.

## Parser canonico

### Processed / Parquet canonico

Saida do parser em `data/processed/<Source>/`. As quatro tabelas comuns sao
`conversations`, `messages`, `tool_events` e `branches`; o schema em
`src/schema/models.py` e a fronteira entre captura e analise.

### Branch

Caminho linear de uma conversa com arvore de mensagens. Uma conversa sem fork
tem uma branch principal; em um fork, cada continuacao vira uma branch com
referencia a sua origem. Apenas uma e a branch ativa da conversa.

### ToolEvent

Linha em `tool_events.parquet` para uma operacao nao conversacional, como
busca, execucao de codigo, canvas, deep research, geracao de imagem, citacao
ou uso de arquivos. Mensagens de ferramenta nao entram em `messages.parquet`,
que contem apenas mensagens de usuario e assistente.

### Asset

Linha em `assets.parquet` que indexa metadados de um arquivo observado ou
preservado, sem incorporar o binario. O caminho, quando disponivel, e relativo
a `data/`; um binario ausente mantem sua linha com
`is_binary_available=False`. `asset_origin` registra quem originou o arquivo
(`user`, `assistant`, `platform`, `imported` ou `unknown`) sem confundir essa
propriedade com o uso do arquivo em uma conversa. O escopo web publicado e
`preserved_web_files`: em Grok, Kimi, Qwen, Gemini, ChatGPT, Claude.ai,
DeepSeek, Perplexity e NotebookLM, toda representacao de arquivo elegivel
preservada em raw/merged vira um Asset canonico, e as demais representacoes
observadas precisam corresponder a uma regra de exclusao aprovada e auditavel.
O escopo independente das quatro CLIs e `preserved_cli_session_assets`; um path
em ToolEvent, por si so, nao comprova um asset de sessao. A
[matriz de cobertura](asset-coverage.md) registra por fonte as representacoes
incluidas, excluidas e a capacidade do leitor. Adaptadores posteriores nao
devem substituir tabelas de dominio como `project_docs` e outputs do NotebookLM.

### AssetLink

Linha em `asset_links.parquet` que relaciona um `Asset` a uma mensagem,
conversa, projeto, fonte ou output. `role` descreve o uso contextual
(`input`, `output`, `context`, `reference` ou `unknown`), enquanto
`content_block_index` permite posicionamento inline quando a fonte oferece essa
evidencia. Um mesmo asset pode ter varios vinculos sem duplicar seus metadados.
`Message.asset_paths`, quando materializado para compatibilidade, segue a mesma
convencao de `Asset.asset_path`: cada entrada e relativa a `data/` e nao inclui
o prefixo `data/`.

### Custom GPT e Project

No raw do ChatGPT, `gizmo_id` pode representar duas coisas: prefixo `g-p-*`
identifica Project e vai para `Conversation.project_id`; `g-*` sem esse
prefixo representa um Custom GPT e vai para `Conversation.gizmo_id`.

## Artefatos de execucao

`LAST_CAPTURE.md` e `LAST_RECONCILE.md` sao resumos humanos sobrescritos a
cada run. `capture_log.jsonl` e `reconcile_log.jsonl` sao historicos
append-only, uma linha por execucao, usados para auditoria e baseline.
