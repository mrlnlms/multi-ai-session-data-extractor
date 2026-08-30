# Inventario de armazenamento dos dados

Medicao realizada em **2026-08-30**, depois da reconciliacao e do envio do
snapshot DVC ao Google Drive. Este documento registra a linha de base para
avaliar crescimento, limpeza segura e uma eventual migracao do remoto DVC.

## Resumo executivo

- Os ponteiros DVC atuais referenciam **14.224.006.493 bytes** de arquivos
  logicos (**14,224 GB / 13,247 GiB**).
- O cache DVC local continha **25.466 objetos** somando **11.133.247.362
  bytes** (**11,133 GB / 10,369 GiB**).
- A diferenca ocorre principalmente porque o DVC armazena uma unica vez
  arquivos de conteudo identico que aparecem em mais de uma camada, como os
  assets do NotebookLM presentes em `raw` e `merged`.
- O maior consumidor e o NotebookLM, sobretudo audios e videos. Em seguida
  vem o historico do Claude Code em JSONL.
- Nao ha indicio de que o volume principal seja lixo de instalacao ou cache
  acidental: ele corresponde aos dados capturados, anexos, saidas multimidia
  e snapshots de recuperacao.

O tamanho do cache local nao deve ser interpretado como uma medicao exata do
remoto. O Google Drive pode conter objetos de snapshots historicos que ja nao
estejam no cache local, e o cache local tambem pode reter objetos antigos. Uma
migracao deve medir o destino depois do upload e validar uma restauracao.

## Volume por camada versionada

Os valores abaixo vem do campo `size` dos ponteiros `.dvc`, portanto
representam tamanho logico antes da deduplicacao por conteudo.

| Camada | Bytes | GB decimais | Funcao |
|---|---:|---:|---|
| `data/raw/` | 7.653.908.704 | 7,654 | Captura bruta e assets |
| `data/merged/` | 4.425.785.936 | 4,426 | Estado reconciliado cumulativo |
| `data/external/` | 1.744.546.670 | 1,745 | Exports e snapshots de recuperacao |
| `data/processed/` | 205.008.218 | 0,205 | Parquets por fonte |
| `data/unified/` | 194.756.965 | 0,195 | Parquets consolidados |
| **Total** | **14.224.006.493** | **14,224** | Antes da deduplicacao DVC |

`processed` e `unified` somam apenas cerca de 400 MB. Remove-los ou deixar de
versiona-los produziria pouca economia e reduziria a capacidade de restaurar
o estado analitico exato de cada snapshot.

## Principais consumidores

### NotebookLM

Volume logico observado:

- `raw`: aproximadamente **3,57 GB**;
- `merged`: aproximadamente **3,63 GB**;
- snapshots externos: **623 MB**;
- `processed`: aproximadamente **19 MB**.

Composicao principal de cada uma das arvores `raw` e `merged`:

| Tipo | Quantidade | Volume por arvore |
|---|---:|---:|
| M4A | 133 | 2,244 GB |
| MP4 | 17 | 0,574 GB |
| PPTX | 18 | 0,239 GB |
| PDF | 18 | 0,228 GB |
| WebP | 2.217 | 0,084 GB |

Grande parte desses binarios e identica em `raw` e `merged`. Eles aparecem
duas vezes no tamanho logico do workspace, mas uma unica vez no cache
content-addressed do DVC. Por isso, remover `merged` nao economizaria os 3,63
GB aparentes no remoto.

### Claude Code

`data/raw/Claude Code/` ocupa aproximadamente **2,95 GB**:

| Tipo | Quantidade | Volume |
|---|---:|---:|
| JSONL | 4.860 | 2,513 GB |
| JPG | 2.420 | 0,285 GB |
| PNG | 1.023 | 0,156 GB |

Os JSONLs registram conversas, chamadas de ferramentas e seus resultados.
Esse volume faz parte do historico capturado, nao de uma dependencia
instalada pelo projeto.

### Snapshots externos

| Conjunto | Tamanho |
|---|---:|
| OpenAI GDPR export | 656 MB |
| NotebookLM snapshots | 623 MB |
| Claude.ai snapshots | 378 MB |
| ChatGPT extension snapshot | 53 MB |
| Demais snapshots e saves | 35 MB |
| **Total** | **1,745 GB** |

Essa e a area mais clara para uma auditoria futura, pois combina fontes de
recuperacao historica e inputs ativos. Auditoria nao significa exclusao:
antes de mudar o versionamento, deve-se provar quais arquivos foram
integralmente incorporados ao `raw`/`merged` e definir onde a copia-fonte
continuara preservada.

## Volume logico por tipo de arquivo

Esta contagem percorre o workspace e, portanto, inclui repeticoes logicas
entre `raw`, `merged` e `external`.

| Tipo | Volume aproximado |
|---|---:|
| M4A | 4,922 GB |
| JSONL | 2,619 GB |
| JSON | 1,742 GB |
| MP4 | 1,230 GB |
| PDF | 0,751 GB |
| ZIP | 0,656 GB |
| PNG | 0,640 GB |
| PPTX | 0,478 GB |
| Parquet | 0,400 GB |
| WebP | 0,328 GB |
| JPG | 0,293 GB |

## Google Drive versus Cloudflare R2

O R2 e tecnicamente mais alinhado ao DVC porque oferece uma API de
armazenamento de objetos compativel com S3. As credenciais chamadas de
"tokens" nesse contexto sao chaves de acesso ao bucket (`Access Key ID` e
`Secret Access Key`), nao tokens de modelos de IA. Elas permitem automacao
sem login interativo no navegador e podem ser limitadas ao bucket do projeto.

A migracao em si e simples: criar bucket e credenciais, adicionar um segundo
remote DVC, enviar os objetos e testar uma restauracao limpa. O Drive deve ser
mantido ate essa validacao terminar.

Para a meta de custo estritamente zero, ha uma ressalva: a franquia publicada
do R2 Standard inclui 10 GB-mes, enquanto o cache local observado ja soma
11,133 GB. Na tarifa publicada de US$ 0,015 por GB-mes excedente, somente essa
diferenca representaria aproximadamente US$ 0,017 por mes. Novas capturas e
objetos historicos aumentariam o valor. Portanto, uma migracao completa e fiel
nao pode ser considerada garantidamente gratuita no estado atual.

Referencias:

- [Cloudflare R2 — pricing](https://developers.cloudflare.com/r2/pricing/)
- [Cloudflare R2 — S3 API](https://developers.cloudflare.com/r2/get-started/s3/)
- [DVC — S3-compatible storage](https://dvc.org/doc/user-guide/data-management/remote-storage/amazon-s3)
- [DVC — Google Drive](https://dvc.org/doc/user-guide/data-management/remote-storage/google-drive)

## Decisoes seguras para a proxima sessao

1. Nao executar `dvc gc` durante a auditoria ou migracao.
2. Nao apagar `raw`, `merged` ou `external` para atingir uma franquia.
3. Medir quais objetos do remoto pertencem ao snapshot atual e quais existem
   apenas no historico antes de estimar o tamanho final no R2.
4. Auditar primeiro `data/external/`, classificando cada conjunto como input
   ativo, evidencia de recuperacao ou copia ja incorporada.
5. Decidir explicitamente se o R2 deve guardar o cofre completo ou apenas um
   subconjunto, sem deixar nenhuma fonte com uma unica copia.
6. Se houver migracao, manter Drive e R2 em paralelo ate um `dvc pull` em
   ambiente limpo reproduzir o snapshot esperado.

## Como reproduzir as medidas

```bash
# Tamanho logico declarado pelos ponteiros DVC
rg '^  size:' data/*.dvc data/external/*.dvc

# Ocupacao visivel por camada e plataforma
du -sh data/*
du -sh data/raw/* data/merged/* data/external/*

# Localizacao do cache configurado
.venv/bin/dvc cache dir

# Estado local e remoto; pode exigir OAuth do Google Drive
.venv/bin/dvc status
.venv/bin/dvc status -c -r gdrive_remote
```

Os numeros mudam a cada nova coleta. Ao atualizar este inventario, registrar
a data, manter a unidade explicita (GB decimal ou GiB) e nao confundir tamanho
logico do workspace com objetos unicos do cache/remoto.
