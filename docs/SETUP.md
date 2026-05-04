# Setup detalhado

Guia completo do zero pra ter o projeto rodando e a primeira captura
funcionando. Para visão geral do projeto, ver [README.md](../README.md).

## Pré-requisitos

- **Python ≥3.12** (testado em 3.12 e 3.14)
- **macOS ou Linux** (Windows não testado)
- **~5GB de espaço livre** (depende de quantas conversas você tem)
- **Git** para clonar o repositório

Verifique a versão:

```bash
python3 --version
# Python 3.12.0 ou superior
```

## Instalação

```bash
git clone <url-do-repo>
cd multi-ai-session-data-extractor

# Cria ambiente virtual isolado
python3 -m venv .venv
source .venv/bin/activate

# Instala o pacote em modo editável + dependências de desenvolvimento
pip install -e ".[dev]"

# Instala o navegador Chromium para Playwright (~200MB)
playwright install chromium
```

A partir daqui, sempre que abrir um terminal novo:

```bash
source .venv/bin/activate
```

## Login (1 vez por plataforma)

Cada plataforma precisa de login interativo uma vez. O script abre um
navegador, você loga manualmente, e o profile fica salvo em
`.storage/<plataforma>-profile-<conta>/` (gitignored).

```bash
python scripts/chatgpt-login.py
python scripts/claude-login.py
python scripts/deepseek-login.py
python scripts/gemini-login.py
python scripts/notebooklm-login.py
python scripts/perplexity-login.py
python scripts/qwen-login.py
```

**O que esperar:**

1. Uma janela do Chromium abre na página de login da plataforma.
2. Você completa o login (email, senha, eventualmente captcha ou 2FA).
3. Quando carrega o dashboard/home da plataforma, o script detecta e
   fecha o navegador sozinho — ou você pode fechar manualmente.
4. O profile fica preservado e os syncs subsequentes não pedem login de
   novo (até o cookie expirar — geralmente meses).

**CLIs (Claude Code, Codex, Gemini CLI):** não precisam de login. Os
dados são copiados diretamente do diretório local
(`~/.claude/projects/`, `~/.codex/sessions/`, `~/.gemini/tmp/`).

## Primeira captura

Recomendado começar com 1 plataforma para validar:

```bash
python scripts/chatgpt-sync.py
```

O sync faz tudo em sequência:

1. **Captura** — baixa via API interna, salva em `data/raw/ChatGPT/`.
2. **Download de assets** — imagens (DALL-E, uploads), arquivos de
   projects, etc.
3. **Reconcile** — consolida com captura anterior em
   `data/merged/ChatGPT/`. Conversas que sumiram do servidor ficam com
   `is_preserved_missing=True`.
4. **Parse** (manual, não roda automático) — converte para parquet:

```bash
python scripts/chatgpt-parse.py
```

Isso gera 4-6 parquets em `data/processed/ChatGPT/` no schema canônico.

Repita os syncs para outras plataformas. Depois consolida tudo num
único conjunto cross-platform:

```bash
python scripts/unify-parquets.py
```

Isso gera 11 parquets em `data/unified/`.

## Multi-conta (Gemini, NotebookLM)

Gemini suporta 2 contas Google. NotebookLM suporta 3 (incluindo legacy).

Para Gemini:

```bash
# Login em cada conta separadamente
python scripts/gemini-login.py --account 1
python scripts/gemini-login.py --account 2

# Sync das duas contas
python scripts/gemini-sync.py

# Ou só uma
python scripts/gemini-sync.py --account 1
```

Mesmo padrão para NotebookLM (`--account 1` / `--account 2`).

## Troubleshooting comum

### "Cookie expirado" / "redirect para login" no sync

O cookie da plataforma expirou. Refaça o login:

```bash
python scripts/chatgpt-login.py
```

### ChatGPT abre janela mesmo no sync (não é headless)

Comportamento esperado — Cloudflare detecta clientes sem janela. Idem
para Perplexity. Outras plataformas (Claude.ai, Gemini, NotebookLM,
Qwen, DeepSeek) rodam sem janela visível.

### "Discovery drop detectado" / sync abortado

O extractor protege contra capturas parciais. Se a listagem inicial
caiu mais de 20% comparado com a maior captura histórica, ele aborta
antes de gravar para não corromper o `data/raw/` cumulativo.

Causas comuns:

- Endpoint de discovery instável (ex: `/projects` da OpenAI eventualmente
  retorna 404)
- Cookie expirou e fallback resolve só parcialmente
- Servidor mudou estrutura

Soluções:

```bash
# Tentar de novo (instabilidade transiente geralmente resolve)
python scripts/chatgpt-sync.py

# Investigar manualmente
python scripts/chatgpt-sync.py --dry-run
```

### Sync demora muito

A primeira captura é lenta porque baixa **tudo**. Capturas seguintes
são incrementais e rápidas (segundos para minutos).

Tempos típicos da primeira captura:

| Plataforma | Tempo |
|---|---|
| Claude.ai | 10-30 min |
| ChatGPT | 5-30 min (depende do volume) |
| NotebookLM | 30-90 min (binários grandes — slide decks, audios) |
| Outras | 1-10 min |

### "ModuleNotFoundError" ao rodar scripts

Você esqueceu de ativar o `.venv` ou não está no diretório raiz do
projeto:

```bash
source .venv/bin/activate
cd /caminho/para/multi-ai-session-data-extractor
PYTHONPATH=. python scripts/<script>.py
```

### Perplexity HTTP 403 no sync

Mesma causa do ChatGPT — Cloudflare. O sync já roda com janela visível
para essa plataforma; se mesmo assim der 403, recriar o profile:

```bash
rm -rf .storage/perplexity-profile-default
python scripts/perplexity-login.py
```

### Quero recapturar do zero (descartar incremental)

```bash
python scripts/chatgpt-sync.py --full
```

Isso força refetch de todas as conversas (não só as que mudaram). Ainda
preserva o que estiver em `data/raw/`.

### Quero apagar tudo e começar do zero

```bash
# CUIDADO: apaga raw + merged + processed (mas .storage/ permanece)
rm -rf data/raw data/merged data/processed data/unified
```

Cookies/profile (`.storage/`) não são apagados. Para apagar tudo
inclusive logins:

```bash
rm -rf data/ .storage/
```

## Próximos passos

- **Dashboard local** — `PYTHONPATH=. streamlit run dashboard.py`
- **Documentos descritivos por plataforma** —
  `quarto render notebooks/<plat>.qmd` (ver [operations.md](operations.md))
- **Análise dos parquets** — leia `data/unified/*.parquet` no pandas/DuckDB
- **Limitações conhecidas** — [LIMITATIONS.md](LIMITATIONS.md)
