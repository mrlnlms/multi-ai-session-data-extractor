# Agent memory: preservacao, temporalidade e consulta

## Objetivo

Preservar as memorias mantidas por agentes CLI como documentos derivados e
consultaveis, sem confundi-las com as conversas que lhes deram origem. O
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
fonte viva (~/.codex, ~/.claude ou memoria hierarquica do Gemini CLI)
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

- `memory_id`: identidade estavel baseada em `source` e `relative_path`.
- `source`: `claude_code`, `codex` ou `gemini_cli` no escopo CLI atual.
- `relative_path`: caminho relativo integral na arvore de memory.
- `project_path` e `project_key`: escopo de projeto, quando observado.
- `file_name`, `name`, `description`, `kind`: metadados de consulta.
- `current_version_id`: versao mais recente observada.
- `first_seen_at`, `last_seen_at`: intervalo de observacao pelo extractor.
- `is_preserved_missing`: o documento nao esta mais na fonte viva.
- `account_id`: permanece nulo sem identidade duravel observavel.

### `agent_memory_versions`

Uma linha por conteudo distinto de um documento.

- `version_id`: `memory_id` mais SHA-256 do conteudo.
- `memory_id`, `content_sha256`, `content`, `content_size`.
- `source_modified_at`: `mtime` observado na fonte, nunca renomeado como data
  de criacao.
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

Cada sync calcula o hash antes de atualizar o estado corrente. Conteudo ainda
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
