# Contribuindo

Este projeto aceita contribuições — issues, PRs, novas plataformas,
melhorias de doc.

## Como reportar um problema

1. Verifique se o problema já está em [LIMITATIONS.md](LIMITATIONS.md).
   Algumas coisas são limitações conhecidas (não bugs).
2. Reproduza o problema com o último estado do código (`git pull`).
3. Abra uma issue com:
   - Plataforma afetada (ex: ChatGPT, Claude.ai)
   - Comando exato que rodou
   - Erro completo (stderr, traceback)
   - Versão Python (`python3 --version`)
   - macOS ou Linux

Para vulnerabilidades de segurança, ver [SECURITY.md](SECURITY.md).

## Como fazer um Pull Request

1. **Fork + branch.** Não trabalhe em `main`.
2. **Rode os testes** antes de submeter:
   ```bash
   PYTHONPATH=. .venv/bin/pytest
   ```
   Todos os 440+ testes precisam passar.
3. **Adicione testes** para mudanças de comportamento. Padrões em
   `tests/parsers/test_*.py`.
4. **Mantenha o estilo** do código existente. Não há linter automático;
   siga o que já está lá.
5. **Commit messages** em português ou inglês, no estilo conventional
   commits (`feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`,
   `test: ...`).
6. **Atualize a documentação** quando aplicável (CLAUDE.md tem o estado
   geral; docs/ tem detalhes por área).

### Antes do PR

- [ ] Testes passam (`pytest`)
- [ ] Sem credenciais commitadas (`git diff` limpo)
- [ ] Mudança documentada onde apropriado
- [ ] Commits assinados com seu nome real

## Adicionando uma plataforma nova

O playbook completo está em
[parser-v3/platform-replication-plan.md](parser-v3/platform-replication-plan.md).
Resumo das fases:

1. **Pasta única cumulativa** em `data/raw/<NovaPlataforma>/`
2. **Sync orquestrador** (`scripts/<plat>-sync.py`) com flags padrão
   (`--full`, `--no-binaries`, `--no-reconcile`, `--dry-run`)
3. **Validação CRUD UI** — testar empiricamente: rename, delete, pin,
   archive (quando aplicáveis); documentar comportamento em
   `docs/platforms/<plat>/server-behavior.md`
4. **Empirical findings** + **fixtures** sanitizadas em
   `tests/extractors/<plat>/fixtures/`
5. **Parser canônico** em `src/parsers/<plat>.py` no schema v3.2
   (ver `src/schema/models.py`)
6. **Script CLI parse** (`scripts/<plat>-parse.py`)
7. **Validação cruzada** com parser legacy (se houver)
8. **Quarto descritivo** — adicionar entrada em `notebooks/<plat>.qmd`
   reusando o template em `notebooks/_template.qmd`

ChatGPT é a referência viva — copie a estrutura, adapte o mínimo
necessário. Divergência semântica vs ChatGPT precisa de justificativa.

## Padrões do projeto

### Idioma

- **Código:** inglês (nomes de funções, variáveis, classes)
- **Comentários e docs:** português ou inglês — seja consistente dentro
  do arquivo
- **Commit messages:** português ou inglês

### Estilo de código

- Tipo hints onde ajudam (não obrigatório em tudo)
- Docstrings em funções públicas e em casos com lógica não-óbvia
- `from __future__ import annotations` no topo de novos módulos
- Sem linter configurado — siga o estilo dos arquivos existentes

### Testes

- `tests/` mirrors `src/` (`tests/parsers/test_<X>.py` pra
  `src/parsers/<X>.py`)
- Use fixtures sanitizadas em `tests/extractors/<plat>/fixtures/` para
  testar parsing — não commite dados pessoais reais
- Testes devem rodar em <5s no total. Se um teste é lento, ou ele
  precisa ser quebrado, ou justifique no docstring

### Schema canônico

`src/schema/models.py` define a estrutura — `Conversation`, `Message`,
`ToolEvent`, `Branch`. Mudanças no schema são **breaking changes** —
discuta numa issue antes de propor PR.

Schema atual: v3.2 (introduziu `capture_method` em Conversation).

### Princípios inegociáveis

(Vale a pena ler antes de propor mudanças que toquem essas áreas:
[README.md#princípios](../README.md#princípios))

1. **Capturar uma vez, nunca rebaixar.** Hardlink primeiro, baixar
   delta depois.
2. **Preservation acima de tudo.** Conversas/arquivos deletados no
   servidor permanecem locais com `is_preserved_missing=True`.
3. **Schema canônico é a fronteira.** Particularidades de plataforma
   não vazam para a etapa de análise.
4. **Aborto cedo (fail-fast)** em casos suspeitos — discovery <80% do
   histórico, etc.

## Onde achar contexto

- [README.md](../README.md) — visão geral
- [CLAUDE.md](../CLAUDE.md) — estado completo, para LLMs/agentes
  trabalhando no projeto
- [docs/README.md](README.md) — índice da documentação
- [docs/glossary.md](glossary.md) — termos do projeto
- [docs/platforms/](platforms/) — comportamento empírico por plataforma
- [docs/parser-v3/](parser-v3/) — design do parser canônico
- [docs/dashboard/](dashboard/) — dashboard Streamlit

## Comportamento esperado

Issues e PRs serão revisados quando o mantenedor tiver tempo. Não há
SLA. Para mudanças grandes, abra uma issue de discussão antes de
investir tempo em código.

Se a contribuição não se encaixar no escopo do projeto (ex: features de
análise interpretativa — sentiment, clustering, topic detection — que
explicitamente não pertencem aqui), ela pode ser fechada sem merge.
Discutir cedo evita retrabalho.
