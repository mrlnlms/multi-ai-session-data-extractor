# Operações — comandos comuns no terminal

Pra rodar o pipeline das 7 plataformas sozinho, sem depender de mim. ChatGPT
serve de referência viva — as outras seguem o mesmo padrão com pequenas
adaptações por plataforma.

---

## Pré-requisito: ativar venv

Em qualquer comando abaixo, ou:
- Use o python do venv direto: `.venv/bin/python` (jeito mais explícito)
- Ou ative o venv na sessão: `source .venv/bin/activate` (depois é só `python`)

Os exemplos abaixo usam `.venv/bin/python` por clareza.

---

## Sync por plataforma

Cada plataforma tem seu próprio orquestrador (`<plat>-sync.py`). Captura +
reconcile + (assets, quando aplicável) em uma rodada. Incremental por padrão.

### ChatGPT

```bash
PYTHONPATH=. .venv/bin/python scripts/chatgpt-sync.py --no-voice-pass
```

### Claude.ai

```bash
PYTHONPATH=. .venv/bin/python scripts/claude-sync.py
# Se sync deixou gaps por timeout transiente:
PYTHONPATH=. .venv/bin/python scripts/claude-refetch-known.py
```

### Perplexity

```bash
PYTHONPATH=. .venv/bin/python scripts/perplexity-sync.py
```

### Qwen

```bash
PYTHONPATH=. .venv/bin/python scripts/qwen-sync.py
```

### DeepSeek

```bash
PYTHONPATH=. .venv/bin/python scripts/deepseek-sync.py
```

### Gemini (multi-conta)

```bash
# Default: roda ambas contas (account-1 + account-2) em sequencia
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py

# Ou apenas uma conta
PYTHONPATH=. .venv/bin/python scripts/gemini-sync.py --account 1
```

### NotebookLM

Multi-conta (3 contas: account-1 en, account-2 pt-BR, account-3 legacy more.design):

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py             # ambas contas web
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py --account 1 # so account-1
```

---

## Detalhes do ChatGPT (referência)

ChatGPT tem mais flags porque é a plataforma mais madura. Outras seguem
um subconjunto destas.

**Flags úteis:**

| Flag | O que faz |
|---|---|
| `--no-voice-pass` | Pula varredura de mensagens de áudio (mais rápido) |
| `--dry-run` | Só descoberta, não baixa nem reconcilia. Bom pra ver quantas convs o servidor mostra |
| `--full` | Refetcha todas as convs (brute force, demora) |
| `--no-binaries` | Pula download de assets e project sources |
| `--no-reconcile` | Pula a etapa final de reconcile |
| `-v` | Verbose (logs DEBUG) |

**O que esperar de uma run normal (incremental):**
- Browser abre (ChatGPT exige headed por causa de Cloudflare)
- Discovery descobre N convs (ex: 1168)
- Fetch baixa só o delta (ex: 1 conv nova)
- Hardlink etapa NÃO acontece mais (pasta única, não precisa)
- Asset download pula tudo que já existe
- Reconcile gera novo `chatgpt_merged.json`

---

## Etapas individuais (quando quiser rodar só uma parte)

```bash
# 1. Login (1x por conta, abre browser)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-login.py

# 2. Captura só (sem assets/sources/reconcile)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-export.py

# 3. Download de assets
PYTHONPATH=. .venv/bin/python scripts/chatgpt-download-assets.py data/raw/ChatGPT

# 4. Download de project sources
PYTHONPATH=. .venv/bin/python scripts/chatgpt-download-project-sources.py data/raw/ChatGPT

# 5. Reconcile (raw → merged)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-reconcile.py data/raw/ChatGPT
```

---

## Ver status sem rodar nada

```bash
# Última captura — quando + counts
cat data/raw/ChatGPT/LAST_CAPTURE.md

# Último reconcile — total de convs, preserved, etc
cat data/merged/ChatGPT/LAST_RECONCILE.md

# Histórico cumulativo de capturas (1 linha por run)
cat data/raw/ChatGPT/capture_log.jsonl

# Histórico cumulativo de reconciles
cat data/merged/ChatGPT/reconcile_log.jsonl

# Total de convs no merged (Python one-liner)
.venv/bin/python -c "import json; d=json.load(open('data/merged/ChatGPT/chatgpt_merged.json')); print(f'{len(d[\"conversations\"])} convs')"
```

---

## Testes

```bash
# Roda toda a suíte
PYTHONPATH=. .venv/bin/pytest tests/ -v

# Só testes do ChatGPT
PYTHONPATH=. .venv/bin/pytest tests/extractors/chatgpt/ tests/reconcilers/test_chatgpt.py tests/test_chatgpt_sync.py -v

# Excluir parsers (que falham por pyarrow ausente — não bloqueante)
PYTHONPATH=. .venv/bin/pytest tests/ --ignore=tests/parsers
```

---

## Rollback do merged (worst case)

Se um reconcile produzir resultado errado e quiseres voltar:

```bash
# 1. Backup automático sempre — antes de qualquer reconcile manual:
cp data/merged/ChatGPT/chatgpt_merged.json /tmp/merged-backup-$(date +%Y%m%d-%H%M).json

# 2. Se algo der errado, restaurar:
cp /tmp/merged-backup-YYYYMMDD-HHMM.json data/merged/ChatGPT/chatgpt_merged.json
```

---

## Setup do zero (em outra máquina ou apagou o `.venv/`)

```bash
cd /caminho/do/projeto
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# Login (1x por conta, por plataforma)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-login.py
PYTHONPATH=. .venv/bin/python scripts/claude-login.py
PYTHONPATH=. .venv/bin/python scripts/perplexity-login.py
PYTHONPATH=. .venv/bin/python scripts/qwen-login.py
PYTHONPATH=. .venv/bin/python scripts/deepseek-login.py
PYTHONPATH=. .venv/bin/python scripts/gemini-login.py --account 1
PYTHONPATH=. .venv/bin/python scripts/gemini-login.py --account 2

# Primeira captura por plataforma (cheia, demora)
PYTHONPATH=. .venv/bin/python scripts/chatgpt-sync.py --no-voice-pass
PYTHONPATH=. .venv/bin/python scripts/claude-sync.py
# ... idem outras
```

## Render Quarto descritivo (HTML self-contained)

Após `<plat>-parse.py` (ou `<cli>-copy.py` + `<cli>-parse.py`), gerar HTML
descritivo. Os 14 qmds compartilham `notebooks/_template.qmd` — adicionar
secao nova mexe em 1 lugar so.

```bash
# Plataformas web (7)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/claude-ai.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/perplexity.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/qwen.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/deepseek.qmd

# CLIs (3) — dado local, sem captura web
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/claude-code.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/codex.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/gemini-cli.qmd

# Gemini multi-conta (consolidado + 2 per-account)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/gemini.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/gemini-acc-1.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/gemini-acc-2.qmd

# NotebookLM multi-conta (consolidado + 2 per-account + 1 legacy)
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm-acc-1.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm-acc-2.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm-legacy.qmd
```

Output em `notebooks/_output/<plat>.html` (gitignored, ~40MB self-contained,
~20-60s cada).

**Overviews cross-plataforma** (a partir de `data/unified/`):

```bash
# Materializar unified primeiro (depois de qualquer <plat>-parse.py)
PYTHONPATH=. .venv/bin/python scripts/unify-parquets.py

# Renderizar os 4 overviews
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview.qmd      # todas as 10 sources
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-web.qmd  # 6 web
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-cli.qmd  # 3 CLIs
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview-rag.qmd  # NotebookLM
```

**Servir local:**

```bash
./scripts/serve-qmds.sh           # sobe (default = start)
./scripts/serve-qmds.sh status    # rodando ou parado?
./scripts/serve-qmds.sh open      # abre 15 abas no browser
./scripts/serve-qmds.sh stop      # para
./scripts/serve-qmds.sh restart   # stop + start

# Variaveis (opcionais):
PORT=8766 ./scripts/serve-qmds.sh         # porta diferente
OUTPUT_DIR=other ./scripts/serve-qmds.sh  # outro dir
```

PID + log gravados em `.serve-qmds.{pid,log}` (gitignored). Servidor sobe
em background — fecha terminal e continua rodando ate `stop`.

**Helpers e testes:** `src/parsers/quarto_helpers.py` cobre setup
(setup_views_with_manual + setup_notebook), schema/query (has_col/has_view/
table_count) e display (fmt_pct/fmt_int/safe_int/show_df/plotly_bar). Testes
em `tests/parsers/test_quarto_helpers.py` (40 testes).

---

## Sintomas comuns e o que significam

| Sintoma | Significado |
|---|---|
| `Discovery: total=1168` | Servidor mostra 1168 convs agora |
| `added=N` no reconcile_log | N convs novas capturadas |
| `preserved_missing=N` | N convs sumiram do servidor mas estão preservadas localmente |
| `RECONCILER ABORTOU: Queda drastica` | Discovery caiu mais de 50% — algo está errado, investigar |
| `Discovery atual=850, baseline=1168 — abortando` | Fail-fast disparou (servidor flakey, não-comum) |
| Browser abre durante captura | Esperado em ChatGPT/Perplexity (Cloudflare). Anormal nas outras |
| `ETIMEDOUT` no log | Timeout de rede no servidor. Tentar de novo depois |
| `8 assets failed` no download-assets | Esperado — 8 assets são irrecuperáveis (parents deletados no servidor há tempo) |

Pra terminologia (`discovery`, `merged`, `baseline`, etc): ver [glossary.md](glossary.md).
