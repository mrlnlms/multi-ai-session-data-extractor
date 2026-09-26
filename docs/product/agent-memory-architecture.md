# Agent memory: preservacao, temporalidade e consulta

## Objetivo

Preservar as memorias mantidas por agentes CLI e as memorias/instrucoes
explicitamente expostas por plataformas web como registros consultaveis,
com tipo e proveniencia separados das conversas que lhes deram origem. O
contrato deve capturar todas as versoes observadas daqui para frente e permitir
reconstruir o passado quando houver evidencia, sempre registrando a base e a
confianca de cada inferencia.

## Principios

1. Conteudo observado e preservado; uma versao nova nunca apaga uma versao
   anterior do acervo consultavel.
2. Conversas sao evidencia primaria. Memorias sao documentos derivados que
   podem resumir, repetir ou reinterpretar conversas.
3. Datas observadas, inferidas e desconhecidas permanecem distinguiveis.
4. Ausencia de evidencia resulta em `NULL`, nao em uma data inventada.
5. A melhor data reconstruida pode ser exposta para consulta, mas sempre junto
   de `basis` e `confidence`.
6. O conteudo historico ja preservado pode ser reconstruido a partir de
   metadados do arquivo, sidecars, nomes, conteudo explicitamente datado e
   historico DVC/Git. A documentacao da regra faz parte do dado.

## Modelo conceitual

```text
fonte viva (arquivos CLI ou respostas nativas de memoria/instrucoes web)
        |
        | observacao de captura
        v
AgentMemory (identidade logica e estado corrente)
        |
        | 1:N por mudanca real de conteudo
        v
AgentMemoryVersion (versao imutavel, identificada por SHA-256)
        |
        | 1:N evidencias temporais
        v
AgentMemoryTemporalEvidence (observacao ou inferencia auditavel)
```

### `agent_memories`

Uma linha por documento logico.

- `memory_id`: identidade estavel baseada em `source` e caminho relativo no
  CLI; no ChatGPT inclui UUID da conta e ID nativo ou superficie observada.
- `source`: as fontes CLI com memoria demonstrada e as plataformas web
  `chatgpt`, `claude_ai`, `perplexity`, `qwen` e `gemini`.
- `relative_path`: caminho CLI ou localizador de captura web relativo ao raw
  da conta; pode incluir um JSON pointer para uma entrada da resposta.
- `project_path` e `project_key`: escopo de projeto, quando observado.
- `file_name`, `name`, `description`, `kind`: metadados de consulta.
- `current_version_id`: versao mais recente observada.
- `first_seen_at`, `last_seen_at`: intervalo de observacao pelo extractor.
- `is_preserved_missing`: o documento nao esta mais na fonte viva.
- `account_id`: UUID do catalogo para plataformas web; permanece nulo sem
  identidade duravel observavel no CLI. Em Claude.ai, `project_key` registra o
  UUID do projeto quando a memoria pertence a um Project.

### `agent_memory_versions`

Uma linha por conteudo distinto de um documento.

- `version_id`: `memory_id` mais SHA-256 do conteudo.
- `memory_id`, `content_sha256`, `content`, `content_size`.
- `source_modified_at`: timestamp nativo de atualizacao ou `mtime` observado
  na fonte CLI, nunca renomeado como data de criacao.
- `source_birth_at`: birth time do filesystem quando observavel, com sua
  limitacao de portabilidade explicita.
- `first_seen_at`, `last_seen_at`, `captured_at`.
- `effective_created_at`, `effective_updated_at`: melhores estimativas para
  consulta.
- `created_at_basis`, `updated_at_basis`: origem da estimativa.
- `created_at_confidence`, `updated_at_confidence`: `high`, `medium`, `low` ou
  `unknown`.

### `agent_memory_temporal_evidence`

Uma linha por evidencia usada na reconstrucao temporal.

- `evidence_id`, `memory_id`, `version_id`.
- `evidence_type`: por exemplo `source_mtime`, `source_birthtime`,
  `first_observed`, `dvc_revision`, `git_revision`, `filename_timestamp` ou
  `explicit_content_timestamp`.
- `timestamp`, `confidence`, `locator` e `details_json`.
- `is_inference`: distingue observacao direta de inferencia.

## Identidade e sobreposicao

O caminho relativo integral participa da identidade. Dois arquivos com o
mesmo basename em subpastas diferentes nao colidem. Conteudos iguais em
documentos distintos continuam sendo documentos distintos, mas o SHA-256
permite detectar duplicacao sem elimina-la. Nenhuma deduplicacao semantica
apaga registros.

No ChatGPT, `chatgpt:<account_id>:saved_memories/<native_id>` identifica cada
entrada, escapando o ID nativo para nao confundi-lo com segmentos de caminho.
Resumo e instrucoes usam superficies estaveis por conta. O localizador de
uma captura nao participa da identidade logica; duas capturas iguais atualizam
as evidencias de observacao da mesma versao. O SHA-256 usa o texto UTF-8 da
entrada ou o JSON completo serializado deterministicamente para resumo e
instrucoes. A resposta original continua preservada no raw.

Os tipos web em `kind` sao `saved_memory`, `project_memory`, `memory_summary`,
`account_instructions`, `project_instructions` e `legacy_export`. Eles mantem distintas as memorias
nativas, a sintese exibida pela plataforma e as instrucoes explicitas da conta.
As colunas das tres tabelas permanecem compativeis com as fontes CLI; apenas
esses valores de `kind` foram acrescentados. Unify, dashboard e Quarto consomem
essas tabelas, sem promover instrucoes a memorias nativas.

No ChatGPT, `project_instructions` usa o ID nativo do Project em `project_key`
e identidade `chatgpt:<account_id>:project_instructions/<project_id>`. O texto
vem somente de `gizmo.instructions` em snapshots completos e verificados de
`GET /backend-api/gizmos/{project_id}`. A data de criacao/atualizacao da
projecao e de observacao da captura, nao um timestamp nativo das instrucoes.
`memory_scope` e `memory_enabled` permanecem no raw nativo e na evidencia da
observacao; nao produzem documentos `AgentMemory` nem itens de memoria de
Project. Uma lista parcial de Projects nao estabelece ausencias.

## Projecao web do Claude.ai

O sistema Melange expoe uma lista de topicos com `memory_id` nativo e caminho,
seguida da leitura individual de cada topico. O coletor preserva lista,
configuracao de modo, respostas individuais e hashes em capturas imutaveis por
conta. Uma captura so e completa quando o modo e `melange` e todas as leituras
terminam; capturas parciais nao provam que um topico desapareceu. O parser
valida os hashes, usa `memory_id` como identidade estavel e o caminho
`/projects/<UUID>/...` para distinguir memoria de projeto. Conteudo e versoes
sao deduplicados por SHA-256; `updated_at` nativo e evidencia de atualizacao,
enquanto a data de criacao fica limitada a primeira observacao. O Markdown
classico anterior fica como `legacy_export`, sem subdivisao inventada.

As capturas locais de 2026-09-25 cobrem 149 topicos nas duas contas, dos quais
124 sao de projeto, mais dois Markdown legados. Os tres exports estruturados
datados em `data/external/claude-ai-snapshots` foram atribuidos a segunda
conta Claude.ai catalogada por identidade exportada e sobreposicao de UUIDs
de Project. O parser oficial agora projeta suas 38 strings classicas de
Project e uma string de conversa da conta como `legacy_export`, com UUID de
Project em `project_key` quando aplicavel: 39 documentos, 41 versoes e 117
evidencias de data de snapshot. O conteudo classico nao se mistura aos topicos
Melange, e a data do diretorio e evidencia de precisao diaria, nao timestamp
nativo de criacao/edicao. O Parquet Claude.ai passou a 190 documentos de
memoria. Nao foi observada uma exclusao real de topico Melange; a regra
`is_preserved_missing` sera exercida por listas completas futuras.

## Projecao web do Perplexity

A colecao account Memory usa `KnowledgeContextKnowledgeRelayQuery` com paginas
`memoryCategories[].items.edges[].node`. Cada pagina GraphQL inteira e
preservada em raw com hash, cursor e captura datada. So uma paginacao completa,
sem erro GraphQL, status nao-OK ou ID duplicado, pode estabelecer ausencias.
`perplexity:<account_id>:<native_id>` identifica o registro; `displayValue`
fornece o conteudo e `updatedAt` a evidencia nativa de atualizacao. A criacao
e somente a primeira observacao. `sourceConversations` permanece metadado
nativo, sem foreign key presumida. Brain, instrucoes de projeto, AI Profile e
configuracoes de Memory nao sao registros dessa colecao.

A primeira captura local de 2026-09-25 continha um registro e nao demonstrou
mudanca nem remocao real; versoes e `preserved_missing` tem testes de contrato.

## Projecao web do Gemini

`ZKcapf` expoe Instructions for Gemini como lista de itens com ID nativo,
conteudo, pares temporais posicionais e campos de estado/tipo. Capturas
imutaveis sao referenciadas por hash em `instructions/observations.jsonl` por
conta. O parser valida hash e formato, identifica cada item por
`gemini:<account_id>:instructions/<native_id>` e projeta `account_instructions`.
So uma lista completa e validada pode marcar um item conhecido como
`is_preserved_missing`; resposta ausente ou com formato alterado nao vira
lista vazia. A primeira versao preservada da conta 1 foi seguida por uma
lista vazia apos exclusao pelo proprietario; as contas 2 e 3 foram observadas
vazias em 2026-09-25.

Os pares de tempo nativos sao evidencias `native_timestamp_field_2` e
`native_timestamp_field_4`. Como a semantica de criacao/atualizacao nao foi
comprovada, datas efetivas usam `first_observed` e `last_observed`. A Memory
aprendida de conversas continua distinta: seu controle habilitado nao expoe
uma lista de registros inspecionaveis no probe delimitado.

## Projecao web do ChatGPT

O parser verifica os hashes de cada snapshot completo e ordena as capturas
por `captured_at`. Dano em uma captura completa interrompe a projecao, em vez
de reduzir silenciosamente o acervo. Capturas incompletas e diretorios de
staging nao substituem o estado corrente. Uma lista de memorias completa e
vazia marca as entradas conhecidas como `is_preserved_missing`; suas versoes
continuam consultaveis. A ausencia e avaliada somente para entradas da lista,
sem inferir exclusao de instrucoes ou de resumo a partir de falha de captura.

`created_timestamp`, `last_updated.timestamp` e `updated_at` sao evidencias
nativas independentes. Epochs numericos sao lidos em segundos UTC;
`updated_at`, observado como data sem hora, tem confianca `medium`.
O timestamp de `last_updated` tem preferencia para atualizacao. Na falta de
criacao nativa, a primeira observacao e exposta com `basis=first_observed`.
No resumo, `generatedAtIso` fornece a evidencia de geracao. Instrucoes sem
timestamp usam observacao; mtimes do checkout nunca completam datas web.

Cada evidencia aponta para o arquivo/entrada raw e preserva os metadados
nativos em `details_json`, inclusive `conversation_id` quando fornecido.
A presenca desse campo nao estabelece uma relacao de origem validada; nao
e criada uma foreign key para conversas. O resumo conserva `followUps` no
JSON, sem inferir que seus prompts sejam referencias a conversas.

Exports correntes servem de fallback quando nao ha snapshot completo daquela
superficie, com data de captura desconhecida. Exports estruturados anteriores
podem acrescentar versoes sem data a identidades nativas ja conhecidas.
Markdown e representacoes sem identidade demonstravel ficam como
`legacy_export`, separados por hash e sem dividir bullets em memorias nativas.
Copias de bytes ja presentes em snapshots validados nao criam novos registros.
Checksum e stream SSE continuam como evidencia de captura; o documento de
resumo projetado e o JSON completo do evento `done`.

O comando de parse inclui contas que possuem apenas memorias no raw, mesmo
sem conversas em merged. A unificacao usa as mesmas tres tabelas e suas chaves
compostas com `account_id`. Nao ha uma nova tabela ou alteracao nas colunas
publicadas; consumidores que enumeram valores de `kind` devem aceitar os
novos tipos.

Na unificacao, as colunas temporais dessas tres tabelas sao normalizadas para
UTC com precisao de nanossegundos antes do concat. Isso preserva a precisao
dos timestamps web ao combinar Parquets CLI em microssegundos e colunas
inteiramente nulas; os valores e as datas desconhecidas permanecem intactos.

## Regras temporais

Ordem inicial de preferencia para `effective_created_at`:

1. timestamp de criacao explicito e estruturado no proprio documento;
2. primeira observacao registrada pelo extractor;
3. primeira revisao DVC/Git em que o mesmo conteudo e demonstravel;
4. birth time observado na fonte viva;
5. timestamp inequivoco no nome do arquivo;
6. data explicitamente declarada no conteudo, marcada como inferencia;
7. `NULL`.

`source_modified_at` permanece separado. Ele pode alimentar
`effective_updated_at`, mas nao deve preencher silenciosamente
`effective_created_at`. Quando duas evidencias discordarem, ambas permanecem
na tabela de evidencias e a regra deterministica escolhe a melhor estimativa.

## Captura futura

No CLI, cada sync calcula o hash antes de atualizar o estado corrente. Conteudo ainda
nao observado e gravado uma unica vez em uma area imutavel de versoes no raw.
Um sync sem mudanca apenas atualiza `last_seen_at`. Se o arquivo desaparecer, a
ultima versao e mantida e o documento recebe `is_preserved_missing=True`.

O manifesto de captura deve ser escrito atomicamente e manter por documento:
primeira e ultima observacao, metadados da fonte e sequencia de hashes. O
parser deve depender desse manifesto e das versoes imutaveis, nao do mtime do
checkout restaurado.

No Gemini CLI, o coletor preserva os arquivos de contexto configurados
(por padrao `GEMINI.md`) no escopo global e nos projetos ja observados em
`~/.gemini/tmp/*/.project_root`, alem do `MEMORY.md` privado quando ele aparece
no estado por projeto. Configuracao geral e credenciais nao sao copiadas. O
Antigravity CLI 1.1.22 observado nao expoe documento de memoria duravel: seu
diretorio `knowledge/` contem apenas um lock vazio, enquanto Markdown em
`brain/` e produto de conversas e permanece classificado como artefato, nao
como `AgentMemory`.

## Reconstrucao do passado

A migracao inicial cria uma versao para cada arquivo ja preservado. Ela pode
consultar evidencia local e historica disponivel, mas nao exige que toda data
seja recuperada. Toda inferencia produz uma linha de evidencia e nunca altera
o arquivo original. Reexecucoes sobre a mesma entrada devem produzir os mesmos
IDs, estimativas e niveis de confianca.

## Consulta

Consultas de descoberta podem priorizar `agent_memories` e a versao corrente.
Consultas historicas usam `agent_memory_versions` e exibem a confianca das
datas. Respostas que usem uma memory devem identifica-la como sintese derivada;
quando houver `derived_from` demonstravel no futuro, a interface deve oferecer
o caminho de volta para a conversa ou rollout primario.
