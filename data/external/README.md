# data/external/

Dados cuja aquisicao fica **fora da captura automatizada regular** — preservados
aqui para contexto historico, recuperacao e analise. Diferente de `data/raw/`,
produzido pelos coletores deste projeto, `data/external/` recebe exports
oficiais, snapshots, clippings manuais, copy-paste e snapshots excepcionais de
configuracao.

Alguns conjuntos possuem adaptadores explicitos e podem alimentar
`data/processed/`; isso nao torna sua aquisicao reproduzivel pelo sync normal.
Esses inputs permanecem imutaveis e nao fazem parte da limpeza de copias de
assets em `raw`/`merged`. Nao migrar, deduplicar ou remover esta arvore apenas
porque uma representacao equivalente exista no pipeline programavel.

## Estrutura

```
data/external/
├── manual-saves/                       # clippings, copy-paste e terminal
├── openai-gdpr-export/                 # exports oficiais OpenAI
├── chatgpt-extension-snapshot/         # snapshot via extensao Chrome
├── claude-ai-snapshots/                # snapshots pre-extractor
├── deepseek-snapshots/                 # snapshot historico DeepSeek
├── notebooklm-snapshots/               # arquivo historico lido pelo parser oficial
├── perplexity-orphan-threads/          # threads historicas fora da discovery atual
├── deep-research-md/                   # exports manuais em Markdown
├── grok-snapshots/                     # export oficial xAI Grok
├── claude-code-config-snapshots/       # snapshot explicito de configuracao
├── codex-config-snapshots/             # snapshot explicito de configuracao
└── gemini-config-snapshots/            # snapshot explicito de configuracao
```

## Categorias

### manual-saves/ ✅ parsável

Convertido para Parquets canonicos pelo comando
`PYTHONPATH=. .venv/bin/python -m src.workflows.manual_saves`. Os tres parsers
ficam em `src/importers/manual/`:

- **clippings-obsidian** — Obsidian Web Clipper (markdown com YAML frontmatter)
- **copypaste-web** — copy-paste manual (.txt) de chats web
- **terminal-claude-code** — output renderizado do terminal Claude Code (.txt)

Output: `data/processed/<Plataforma>/<source>_manual_<table>.parquet`. Quartos
fazem UNION via `setup_views_with_manual()` em `src/reporting/quarto_helpers.py`.

### Snapshots consumidos por adaptadores

| Conjunto | Consumo atual | Limite |
|---|---|---|
| `notebooklm-snapshots/` | O parser oficial do NotebookLM inclui o acervo historico, salvo uso deliberado de `--without-historical`. | O parser le o snapshot; o sync nao o recaptura. |
| `deepseek-snapshots/` | Evidencia historica e input conhecido da projecao de assets. | Nao substitui a captura atual nem autoriza descarte. |
| `perplexity-orphan-threads/` | Evidencia historica para threads orfas e projecao de assets. | Continua fora da discovery regular. |
| `*-config-snapshots/` | Criados apenas pela operacao explicita `python -m src.capture.cli.snapshot`. | Nao sao profiles ativos nem credenciais de runtime. |

Stats atuais (29 convs / 403 msgs / 75 tool_events):

| Plataforma | Convs | capture_method |
|---|---|---|
| ChatGPT | 21 | manual_clipping_obsidian (20) + manual_copypaste (1) |
| Claude.ai | 2 | manual_clipping_obsidian (1) + manual_copypaste (1) |
| Claude Code | 3 | manual_terminal_cc (3) |
| Gemini | 2 | manual_copypaste (2) |
| Qwen | 1 | manual_copypaste (1) |

### grok-snapshots/ ⏸ blob historico (pipeline usa API)

Export oficial xAI Grok (zip baixado pelo user via UI). TTL 30 dias no
storage do servidor. Estrutura por snapshot:

- `prod-grok-backend.json` — convs/projects/tasks/media_posts (NAO usado;
  extractor via `/rest/app-chat/conversations_v2` retorna 36 campos por
  response vs 7 do export — superior)
- `prod-mc-auth-mgmt-api.json` — profile + sessions com IP/cidade/UA
  (preservado como blob, sem parser canonico)
- `prod-mc-billing.json` — billing balance (vazio em free tier)
- `prod-mc-asset-server/<asset_id>/content` × 44 + profile-picture.webp
  — **redundante:** mesmos binarios baixados via API por
  `src/platforms/grok/extractor/asset_downloader.py` em `https://assets.grok.com/
  <key>` (sha256 bit-identical). Pipeline canonico nao depende deste
  snapshot.

Snapshot mantido apenas como blob historico pra recovery extremo
(conta deletada -> sem acesso aos endpoints).
Detalhes na [análise de paridade do export Grok](../../docs/extractor-engineering/platforms/web/grok/export-parity-2026-05-09.md).

### openai-gdpr-export/ ⏸ preservado (sem parser)

Exports oficiais OpenAI via ferramenta GDPR. Contém `Contact Info/`,
`Financial/`, `User Online Activity/`, `User Profile/`, `report.html`. **Não**
contém conversations parseáveis pro schema canônico (são metadados de billing
+ usage). Preservado como blob histórico.

- `2026-03-27/` — 230MB, primeiro export
- `2026-04-27/` — 396MB descomprimido, segundo export

### chatgpt-extension-snapshot/ ⏸ preservado (sem parser)

Snapshot via extensão Chrome (3rd-party tool). Contém:
- `chatgpt_all_conversations.json` — outro snapshot de convs (potencial cross-validation com extractor)
- `chatgpt_instructions.json` — custom instructions
- `chatgpt_memories.md` — memories

51MB. Preservado pra recuperação. Possível parser futuro pra cross-validar
com `chatgpt_conversations.parquet` do extractor.

### claude-ai-snapshots/ ⏸ preservado (sem parser)

Snapshots brutos Claude.ai pré-extractor — formato simples
(conversations.json + memories.json + projects.json + users.json). Vindos
do projeto pai antes do extractor automatizado existir.

- `2026-03-26/` — 304MB
- `2026-03-30/` — 26MB
- `2026-04-18/` — 30MB

Total 360MB. Possível parser futuro pra cross-validar com extractor atual
(equivalente Claude.ai do que `chatgpt-extension-snapshot/` é pro ChatGPT).

### deep-research-md/ ⏸ preservado (sem parser)

2 exports manuais de Deep Research em markdown:
- `chatgpt-deep-research-metodos-quanti-quali-24mai2025.md`
- `chatgpt-research-rigor-vs-business-velocity.md`

Total 208KB. Preservado. Decisão de criar parser foi adiada — o conteúdo
é output longo de Deep Research sem prompt visível, requer design
específico antes de implementar.

## Convenções de naming

- **Por plataforma + tipo**: `chatgpt-extension-snapshot/`, `claude-ai-snapshots/`,
  `openai-gdpr-export/`
- **Datas no path**: `<categoria>/<YYYY-MM-DD>/` quando há múltiplos snapshots

## Adicionando novas fontes externas

1. Criar pasta `data/external/<categoria>/` com naming descritivo
2. Adicionar entrada em **Categorias** acima documentando o que é
3. Decidir se um adaptador explicito deve ler o conjunto ou se ele fica
   preservado como blob; isso nao muda sua origem externa
4. Se ganhar adaptador:

   - Criar `src/importers/manual/<source>.py` (ou `external/<source>.py`)
   - Atualizar `src/workflows/manual_saves.py` quando o formato pertencer a
     manual saves, ou o parser da plataforma quando for evidencia historica
   - Output em `data/processed/<Plataforma>/<source>_manual_<table>.parquet`

## Retencao

Cada subdiretorio e rastreado por seu proprio ponteiro DVC. Tamanho, idade ou
equivalencia aparente com `raw`, `merged` ou `assets` nao sao autorizacao para
remocao. Uma mudanca futura de politica exige uma decisao explicita sobre este
acervo; a manutencao rotineira do pipeline e o GC do DVC nao reclassificam seu
conteudo.
