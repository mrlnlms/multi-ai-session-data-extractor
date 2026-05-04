# multi-ai-session-data-extractor

Captura e arquivamento das suas próprias sessões em plataformas de AI
(ChatGPT, Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity)
mais ferramentas de linha de comando (Claude Code, Codex, Gemini CLI).
Os dados ficam preservados localmente em formato canônico (parquet),
mesmo se você apagar do servidor.

> **Esta ferramenta é para uso pessoal, com as suas próprias contas.**
> Ela usa as APIs internas das plataformas autenticadas com cookies do
> seu próprio login (acesso que você já tem). Não é uma ferramenta de
> scraping de dados de outros usuários nem de bypass de termos de uso —
> e não deve ser usada assim.

## O problema

Plataformas de AI têm exports oficiais limitados, frequentemente
quebrados, sem garantia de retenção. Você não tem como saber se uma
conversa antiga vai estar acessível daqui a 6 meses, ou se uma feature
nova vai sumir levando dados junto.

Este projeto resolve isso capturando tudo localmente:

- Conversas, projects, knowledge files, artifacts (canvas, deep research
  reports, slide decks)
- Imagens geradas (DALL-E, Nano Banana), uploads do usuário, mind maps
- Mensagens de voz (transcrições), thinking blocks (reasoning), tool calls
- Chats deletados no servidor — preservados localmente para sempre

Output em **parquet** (schema unificado entre todas as 10 fontes), pronto
para análise em pandas/DuckDB/Quarto/o-que-você-preferir.

## Estado atual

Todas as 10 fontes funcionam end-to-end — captura, consolidação,
parsing canônico e visualização descritiva (Quarto):

| Fonte | Tipo | Cobertura |
|---|---|---|
| **ChatGPT** | web | branches, voice, DALL-E, projects, custom GPT |
| **Claude.ai** | web | thinking, tool use+MCP, project_docs com content inline |
| **Perplexity** | web | threads + pages + spaces + 9 tipos de artifacts |
| **Qwen** | web | 8 tipos de chat (search, research, dalle, etc), projects |
| **DeepSeek** | web | R1 reasoning (thinking em ~31% das msgs), token usage |
| **Gemini** | web | multi-conta (2 contas Google), 8 modelos |
| **NotebookLM** | web | multi-conta (3), 9 tipos de outputs (audio, video, slide deck, etc) |
| **Claude Code** | CLI | sessões locais (`~/.claude/projects/`), subagents |
| **Codex** | CLI | sessões locais (`~/.codex/sessions/`), latência exata por tool call |
| **Gemini CLI** | CLI | sessões locais (`~/.gemini/tmp/`) |

**514 testes passando.** Limitações conhecidas e gaps documentados em
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Quickstart

Pré-requisitos: Python ≥3.12, macOS ou Linux. Windows não testado.

```bash
git clone <repo>
cd multi-ai-session-data-extractor
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

Login (1x por plataforma — abre navegador, você loga manualmente, fecha):

```bash
python scripts/chatgpt-login.py
```

Sync (captura + consolidação + parquet em 1 comando):

```bash
python scripts/chatgpt-sync.py
```

Resultado:

- `data/raw/ChatGPT/` — captura crua (cumulativa, mantém binários)
- `data/merged/ChatGPT/` — versão consolidada (mantém também conversas
  apagadas do servidor)
- `data/processed/ChatGPT/*.parquet` — formato canônico para análise

Repita os 2 comandos para outras plataformas (`claude-login.py`,
`gemini-sync.py`, etc). Detalhes em [docs/SETUP.md](docs/SETUP.md).

## Como funciona

```
extractor → reconciler → parser → unify
   raw    →  merged    → processed (per-source) → unified (cross-source)
```

1. **Extractor** baixa via API interna da plataforma (autenticada com seu
   cookie).
2. **Reconciler** consolida o que você capturou agora com o que já tinha
   antes — preservando registros que sumiram do servidor.
3. **Parser** converte o JSON cru em parquet com schema unificado:
   `Conversation`, `Message`, `ToolEvent`, `Branch` (e algumas auxiliares
   por plataforma — `ProjectDoc`, `NotebookLMOutput`, etc).
4. **Unify** consolida os parquets das 10 fontes num único `data/unified/`
   com 11 arquivos parquet (4 canônicos + 7 auxiliares), pronto para
   análise cross-platform.

Schema completo em `src/schema/models.py`. Glossário dos termos do
projeto em [docs/glossary.md](docs/glossary.md).

## Captura: navegador visível ou em segundo plano

Login é sempre com janela visível (1x por plataforma — você precisa logar
manualmente). Captura depois disso varia:

| Plataforma | Captura |
|---|---|
| Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek | Sem janela visível |
| ChatGPT, Perplexity | Janela visível (Cloudflare detecta scraping sem janela) |

Se você rodar Claude.ai/Gemini/NotebookLM/Qwen/DeepSeek e ver janela
abrir durante a captura: tem algo errado (provavelmente cookie expirou).
Para ChatGPT/Perplexity: comportamento esperado.

## Comandos por plataforma

Cada plataforma tem 2-3 scripts em `scripts/`. Padrão:

```bash
python scripts/<plat>-login.py    # 1x — login manual no navegador
python scripts/<plat>-sync.py     # captura + consolidação
```

Flags consistentes em todos os syncs:

- `--full` — força recaptura completa (pula o caminho incremental)
- `--no-binaries` — pula download de assets (imagens, slide decks, etc)
- `--no-reconcile` — pula a consolidação (só captura)
- `--dry-run` — mostra o que faria sem executar

Lista completa de comandos por plataforma:
[docs/operations.md](docs/operations.md).

## Dashboard

Visualização local em Streamlit — totais cross-platform, status por
plataforma, links para os documentos descritivos:

```bash
PYTHONPATH=. streamlit run dashboard.py
```

Abre em <http://localhost:8501>. Read-only sobre o que o sync produziu —
não escreve nem edita.

Detalhes em [docs/dashboard/manual.md](docs/dashboard/manual.md).

## Documentos descritivos (Quarto)

14 documentos por plataforma + 4 visões cross-platform — schema dos
dados, cobertura, distribuições, exemplos. Compartilham um template
único para evitar duplicação.

```bash
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/00-overview.qmd
```

Pra ver localmente os HTMLs gerados:

```bash
./scripts/serve-qmds.sh open
```

## Testes

```bash
PYTHONPATH=. .venv/bin/pytest                    # tudo (514 testes, ~3s)
PYTHONPATH=. .venv/bin/pytest tests/parsers/     # só parsers
```

## Documentação

- [docs/README.md](docs/README.md) — índice completo
- [docs/SETUP.md](docs/SETUP.md) — setup detalhado, primeiro login,
  troubleshooting
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — gaps e limitações conhecidas
- [docs/operations.md](docs/operations.md) — comandos comuns por plataforma
- [docs/glossary.md](docs/glossary.md) — termos do projeto
- [docs/platforms/](docs/platforms/) — comportamento empírico por plataforma
- [docs/SECURITY.md](docs/SECURITY.md) — política de credenciais e ToS
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) — guia para contribuidores

## Princípios

1. **Capturar uma vez, nunca rebaixar.** Quando algo é capturado,
   permanece local. Reruns só baixam novidades.
2. **Preservation acima de tudo.** Conversas/arquivos deletados no
   servidor permanecem locais com flag `is_preserved_missing=True`.
3. **Schema canônico é a fronteira.** Os parsers entregam parquet em
   schema unificado; análise consome parquet. Não há vazamento de
   particularidades de plataforma para a etapa de análise.
4. **Aborto cedo em casos suspeitos.** Se a listagem inicial cair >20%
   versus o histórico, o extractor aborta antes de gravar (proteção
   contra capturas parciais que contaminariam a próxima rodada).

## Licença

MIT — ver [LICENSE](LICENSE).

## Contribuindo

Issues e PRs bem-vindos. Detalhes em
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md), incluindo o playbook de
8 fases pra adicionar plataforma nova.
