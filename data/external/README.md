# data/external/

Dados que **NÃO vêm do extractor automatizado** — preservados aqui pra
contexto histórico, recuperação e análise futura. Diferente de `data/raw/`
(produzido pelos extractors deste projeto), `data/external/` recebe dados
de origens diversas: exports oficiais, snapshots via extensões, clippings
manuais, copy-paste, etc.

## Estrutura

```
data/external/
├── manual-saves/                       # parsável (sync via scripts/manual-saves-sync.py)
│   ├── clippings-obsidian/
│   ├── copypaste-web/
│   └── terminal-claude-code/
├── openai-gdpr-export/                 # GDPR oficial OpenAI
│   ├── 2026-03-27/                     #   primeiro snapshot
│   └── 2026-04-27/                     #   segundo snapshot (mais recente)
├── chatgpt-extension-snapshot/         # snapshot via extensão Chrome (ChatGPT)
│   └── 2026-03-27/
├── claude-ai-snapshots/                # snapshots brutos Claude.ai (pré-extractor)
│   ├── 2026-03-26/
│   ├── 2026-03-30/
│   └── 2026-04-18/
├── deep-research-md/                   # 2 exports manuais Deep Research em .md
└── grok-snapshots/                     # exports oficiais xAI Grok
    └── 2026-05-09/                     #   primeiro snapshot
```

## Categorias

### manual-saves/ ✅ parsável

Convertido pra parquets canônicos via `scripts/manual-saves-sync.py`. Os 3
parsers (`src/parsers/manual/`):
- **clippings-obsidian** — Obsidian Web Clipper (markdown com YAML frontmatter)
- **copypaste-web** — copy-paste manual (.txt) de chats web
- **terminal-claude-code** — output renderizado do terminal Claude Code (.txt)

Output: `data/processed/<Plataforma>/<source>_manual_<table>.parquet`. Quartos
fazem UNION via `setup_views_with_manual()` em `src/parsers/quarto_helpers.py`.

Stats atuais (29 convs / 403 msgs / 70 tool_events):
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
  `src/extractors/grok/asset_downloader.py` em `https://assets.grok.com/
  <key>` (sha256 bit-identical). Pipeline canonico nao depende deste
  snapshot.

Snapshot mantido apenas como blob historico pra recovery extremo
(conta deletada -> sem acesso aos endpoints).
Detalhes em [docs/platforms/grok/export-analysis.md](../../docs/platforms/grok/export-analysis.md).

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
3. Decidir se vira parser ou fica preservado como blob
4. Se virar parser:
   - Criar `src/parsers/manual/<source>.py` (ou `external/<source>.py`)
   - Atualizar `scripts/manual-saves-sync.py` (se aplicável) ou criar sync próprio
   - Output em `data/processed/<Plataforma>/<source>_manual_<table>.parquet`

## Total atual

```
manual-saves/                  1.8MB (parsável)
openai-gdpr-export/            1.0GB (extraídos + zip)
chatgpt-extension-snapshot/     51MB
claude-ai-snapshots/           360MB
deep-research-md/              208KB
grok-snapshots/                 10MB (binarios usados em data/raw/Grok/assets)
                              -------
                              ~1.4GB
```
