# Quarto descritivo — briefing pra implementação (Fase 3 do dashboard)

> **Status: Fase 3.1 IMPLEMENTADA em 2026-04-28.** `notebooks/chatgpt.qmd`
> renderiza em ~20s, HTML self-contained ~52MB, 4 seções entregues
> (§1 Dados, §2 Cobertura, §3 Volumes, §4 Preservation). Comando:
> `QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/chatgpt.qmd`.
> Pendente: Fase 3.2 (template parametrizado quando 2+ plataformas) +
> integração Streamlit (botão "Ver dados detalhados"). Este doc fica como
> histórico do plan.

Briefing curto pra sessão paralela implementar o Quarto descritivo. Output:
notebook(s) `.qmd` que renderiza HTML estático mostrando "o que tem nos
parquets do parser v3", linkado a partir do dashboard Streamlit.

---

## 1. Contexto

### 1.1. Onde encaixa

```
data/processed/<Source>/
├── conversations.parquet           ← parser v3 entrega
├── messages.parquet
├── tool_events.parquet
├── branches.parquet
        ↓
notebooks/<source>.qmd               ← VOCÊ implementa
        ↓ (quarto render)
notebooks/_output/<source>.html      ← consumido pelo dashboard
        ↓
Streamlit linka em "Ver dados detalhados" (Fase 3 do dashboard-plan)
```

### 1.2. Princípio inegociável: **zero trato**

Apresentar dados, **não interpretar**. Counts, distribuições, tabelas de
cobertura, gaps. Sem sentiment analysis, clustering, narrative discovery,
ranking de "qualidade", topic detection.

Quem quer interpretação pesada leva os parquets pra
`~/Desktop/AI Interaction Analysis/`.

### 1.3. Audiência

Pessoa técnica baixou o projeto, rodou sync + parse, abre o HTML pra
**conhecer o dataset** que tem em mãos. Não é dashboard pra leigo, é
profiling pra quem vai analisar depois.

---

## 2. Inspiração — `~/Desktop/AI Interaction Analysis/notebooks/data-profile/`

Esse projeto-mãe **já tem** essa abordagem implementada. 18 notebooks
descritivos no padrão "data profile" — exatamente "zero trato".

### 2.1. Estrutura que eles usam

**Template parametrizado** (`_template.qmd`) + **wrapper por fonte** que
configura constantes:

```python
# 04-chatgpt.qmd (61 linhas — só configura)
SOURCE_KEY = "chatgpt"
SOURCE_FILTER = "WHERE source = 'chatgpt'"
NOTEBOOK_TITLE = "ChatGPT"
COLOR = COLORS.get(SOURCE_KEY)
db = DuckDBManager(_project_root / "data" / "unified")
# ... include do template
{{< include ../_template.qmd >}}
```

```
_template.qmd (598 linhas — todo o conteúdo)
├── §1 Dados disponíveis
│   └── 1.1 Conversas (schema + cobertura + amostra diversificada)
└── §2 Diagnóstico de cobertura
    ├── 2.1 Conversas sem título (com gráfico temporal de gaps)
    ├── 2.2 Cobertura de modelo
    ├── 2.3 Cobertura de account
    ├── 2.4 Cobertura de mode
    └── 2.5 Cobertura de project
```

### 2.2. Stack técnico observado

- **Quarto** com `format: html, code-fold: true, embed-resources: true`
- **DuckDB** queryando parquets via `db.query("SELECT ...")` — perf > pandas
- **Plotly** pra gráficos interativos (`go.Figure`, `go.Bar`, etc)
- **CSS compartilhado** em `_style.css`
- **Cores por source** em config (`src/notebook_config.py: COLORS`)
- Pequenos blocos com `code-summary: "<descrição>"` pra UX do code-fold

### 2.3. Padrões fortes que valem reusar

- **Tabela "Cobertura"**: pra cada campo, mostra `n_preenchido / n_total
  (%)`. Imediato pra ver gaps
- **Amostra diversificada**: em vez de "primeiras 5 linhas", queries com
  CTEs que pegam 1 caso de cada variação relevante (com projeto, sem
  projeto, com modelo, conv mais longa, mais curta, etc)
- **Diagnóstico de gap por campo**: quando há campo com gap, mostrar
  distribuição temporal do gap + perfil dos casos sem dado
- **Callout "Enrichment disponível"**: link pra notebook que resolve o
  gap (no projeto-mãe). **Pra nós: NÃO criar callouts assim — não temos
  enrichment, é parser direto**

### 2.4. O que descartar do padrão deles

O projeto-mãe tem 4 categorias de notebook (eda, analysis, qualitizing,
enrichment) — só **data-profile** entra no nosso escopo. Os outros são
interpretativos. Ignorar.

---

## 3. Estrutura sugerida pro nosso QMD

Adaptado do template do projeto-mãe pra nossos parquets do parser v3.

### 3.1. Por plataforma (`notebooks/<source>.qmd`)

```
§1 Dados disponíveis
├── 1.1 Conversations (1.171 rows × 19 cols)
│   ├── Tabela de schema (campo, tipo, descrição, cobertura)
│   └── Amostra diversificada (com/sem project, com/sem custom GPT,
│       com/sem voice, longa/curta, active/preserved)
├── 1.2 Messages (17.582 rows × 22 cols)
│   ├── Schema + cobertura
│   └── Amostra (cada role: user/assistant, com voice, com asset, hidden)
├── 1.3 ToolEvents (3.109 rows × 12 cols)
│   ├── Schema + cobertura
│   └── Amostra (cada event_type)
└── 1.4 Branches (1.369 rows × 9 cols)
    ├── Schema + cobertura
    └── Amostra (main vs fork, active vs inactive)

§2 Cobertura e gaps
├── 2.1 Cobertura de title em conversations
├── 2.2 Cobertura de model em messages
├── 2.3 Convs sem update_time / convs órfãs
└── 2.4 Asset paths não-resolvidos (ToolEvents com file_path = None)

§3 Volumes e distribuições (zero trato — só counts)
├── 3.1 Conversas por mês (timeline)
├── 3.2 Mensagens por role (user / assistant)
├── 3.3 ToolEvents por event_type (10 categorias)
├── 3.4 Modelos usados (top N)
├── 3.5 Convs em projects vs standalone
├── 3.6 Distribuição de tamanho (msgs por conv — histogram)
└── 3.7 Branches: forks por conv (a maioria tem 1 branch só?)

§4 Preservation (campos canônicos do parser v3)
├── 4.1 Active vs preserved_missing (count + lista)
├── 4.2 last_seen_in_server distribution (quando convs sumiram)
├── 4.3 Custom GPT vs Project (gizmo_id distinction)
└── 4.4 Tabela completa filtrável (DataTable / Plotly Table com search)
```

### 3.2. Cross-plataforma (`notebooks/00-overview.qmd`) — opcional Fase 3.1

Quando 2+ plataformas tiverem QMD próprio, adicionar overview:

```
§1 Volumes cross-plataforma
├── Total convs / msgs / tool_events por source
├── Período coberto (oldest → newest) por source
└── Stack relativo (% de cada source no total)

§2 Heatmap temporal cross-source
└── Atividade por mês × source (qual source ativa quando)

§3 Comparativos descritivos
├── Distribuição de tamanho de conv (boxplot por source)
├── Modelos: distintos por source
└── Coverage: campos preenchidos vs ausentes por source
```

**Não fazer** análise de "qual source é melhor" ou narrativa cruzada.

---

## 4. Stack técnico recomendado

### 4.1. Header padrão do `.qmd`

```yaml
---
title: "ChatGPT — Data Profile"
format:
  html:
    toc: true
    toc-depth: 3
    code-fold: true
    embed-resources: true
    css: _style.css
execute:
  warning: false
  echo: false
---
```

### 4.2. Setup mínimo

```python
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

import pandas as pd
import duckdb
import plotly.graph_objects as go

# DuckDB direto sobre os parquets — perf melhor que pandas pra agregação
con = duckdb.connect()
con.execute(f"""
    CREATE VIEW conversations AS
    SELECT * FROM read_parquet('{_project_root}/data/processed/ChatGPT/conversations.parquet')
""")
con.execute(f"""
    CREATE VIEW messages AS
    SELECT * FROM read_parquet('{_project_root}/data/processed/ChatGPT/messages.parquet')
""")
# ... idem tool_events, branches

SOURCE_COLOR = "#74AA9C"  # ChatGPT green
```

### 4.3. Template parametrizado (futuro)

Quando 2+ plataformas: adotar padrão do projeto-mãe (`_template.qmd` +
wrapper por source que define `SOURCE_KEY`/`SOURCE_FILTER`/`COLOR`).

Por agora (Fase 3 inicial): **só ChatGPT**. Não vale antecipar parametrização.

### 4.4. Exemplo de bloco "schema + cobertura"

Direto do projeto-mãe, adaptado:

```python
#| label: conversations-schema
#| code-summary: "Dicionário de campos — conversations"

coverage = con.execute("""
    SELECT
        COUNT(*) AS total,
        COUNT(title) AS title,
        COUNT(model) AS model,
        COUNT(project_id) AS project_id,
        COUNT(gizmo_id) AS gizmo_id,
        SUM(is_preserved_missing::INT) AS preserved
    FROM conversations
""").df()

total = coverage["total"].iloc[0]
def cov(field):
    n = coverage[field].iloc[0]
    pct = n / total * 100 if total > 0 else 0
    return f"{n:,}/{total:,} ({pct:.0f}%)"

schema = pd.DataFrame([
    {"Campo": "conversation_id", "Tipo": "str", "Descrição": "ID único", "Cobertura": cov("conversation_id")},
    {"Campo": "title", "Tipo": "str?", "Descrição": "Título da conv (gerado pela API)", "Cobertura": cov("title")},
    {"Campo": "model", "Tipo": "str?", "Descrição": "Modelo predominante (gpt-4o, gpt-5, etc)", "Cobertura": cov("model")},
    {"Campo": "project_id", "Tipo": "str?", "Descrição": "g-p-* (project), separado de gizmo_id", "Cobertura": cov("project_id")},
    {"Campo": "gizmo_id", "Tipo": "str?", "Descrição": "g-* (Custom GPT real, não project)", "Cobertura": cov("gizmo_id")},
    {"Campo": "is_preserved_missing", "Tipo": "bool", "Descrição": "True se conv sumiu do servidor", "Cobertura": "—"},
    # ... resto dos 19 campos
])
display(schema.style.hide(axis="index"))
```

---

## 5. Estrutura de arquivos novos

```
notebooks/
├── _style.css                    # CSS compartilhado (copiar do projeto-mãe)
├── chatgpt.qmd                   # Fase 3 inicial: só ChatGPT
└── _output/
    └── chatgpt.html              # gerado por `quarto render`

# (futuro)
├── _template.qmd                 # quando >= 2 plataformas
├── claude.qmd                    # wrapper
├── gemini.qmd                    # wrapper
└── 00-overview.qmd               # cross-plataforma
```

**`_style.css`:** copiar de `~/Desktop/AI Interaction Analysis/notebooks/data-profile/_style.css`
como ponto de partida. Ajustar cor primária se necessário.

---

## 6. Por onde começar — exploração antes de codar

**NÃO começar escrevendo `chatgpt.qmd` direto.** Primeiro abre os parquets
no Positron/Jupyter e EXPLORA por 30-60 min:

```python
import pandas as pd
import duckdb

# Carrega
convs = pd.read_parquet("data/processed/ChatGPT/conversations.parquet")
msgs = pd.read_parquet("data/processed/ChatGPT/messages.parquet")
tools = pd.read_parquet("data/processed/ChatGPT/tool_events.parquet")
branches = pd.read_parquet("data/processed/ChatGPT/branches.parquet")

# Perguntas pra explorar interativamente:
print(convs.dtypes)             # quais campos / tipos
print(convs.isna().sum())       # quais têm gaps
print(msgs["role"].value_counts())
print(tools["event_type"].value_counts())
print(branches["is_active"].value_counts())

# Matrix de cross-stats
con = duckdb.connect()
con.register("convs", convs)
con.register("msgs", msgs)
con.execute("""
    SELECT model, COUNT(*) AS n_msgs
    FROM msgs WHERE role='assistant'
    GROUP BY model ORDER BY n_msgs DESC
""").df()

# Etc — ver o que SURPREENDE, o que GERA pergunta
```

**Decidir o que mostrar baseado no que tu acha relevante.** O perfil
de UX research do user vai querer ver: temporal, distribuição, tabela
filtrável. Sem cluster, sem topic.

Depois de explorar, **monta o `chatgpt.qmd`** pegando o que ressoou.

---

## 7. Integração com o dashboard (Streamlit)

Já planejado em `dashboard-plan.md` §Fase 3. Resumo:

- Streamlit detecta Quarto instalado (`shutil.which("quarto")`)
- Botão "📊 Ver dados detalhados" no drill-down de plataforma
- Botão dispara `subprocess.Popen(["quarto", "render", "notebooks/chatgpt.qmd"])`
- Streamlit detecta HTML stale via mtime de parquet vs HTML, re-renderiza
  se necessário
- Link `<a target="_blank">` abre HTML em nova aba

**Esse plumbing já está documentado.** Sessão Quarto não precisa se
preocupar com integração — só entregar QMD que renderiza.

---

## 8. Critérios de pronto

### Fase 3.1 (MVP — só ChatGPT)

- ✅ `notebooks/chatgpt.qmd` renderiza com `quarto render` sem erro
- ✅ Output em `notebooks/_output/chatgpt.html` self-contained
- ✅ §1 Dados disponíveis com schema + cobertura das 4 tabelas
- ✅ §2 Cobertura e gaps com pelo menos 3 diagnósticos
- ✅ §3 Volumes e distribuições com pelo menos 4 visualizações
- ✅ §4 Preservation com listagem de preserved_missing
- ✅ Renderização em < 30s (1.171 convs / 17.582 msgs)
- ✅ HTML abre direto no browser (sem servidor)

### Fase 3.2 (template parametrizado, multi-source)

Adiar até segunda plataforma estar com parser pronto.

---

## 9. O que NÃO é objetivo

- ❌ Análise interpretativa (sentiment, clustering, topic, narrative)
- ❌ Sankey, network graph, timeline qualitativa (ficam no projeto-mãe)
- ❌ Enrichment próprio (parser v3 já fez tudo que tinha que fazer)
- ❌ Comparação valorativa entre plataformas
- ❌ Notebooks executáveis pelo usuário final (HTML estático é o output)
- ❌ DuckDB persistido (`.duckdb` file) — usar conexão em memória
- ❌ Cache de queries — render é one-shot
- ❌ Multi-language (português ou inglês — escolher um, manter)

---

## 10. Recursos de referência

**Pra ler antes de codar:**
1. `docs/parser-v3-plan.md` — entender estrutura dos parquets
2. `docs/parser-v3-empirical-findings.md` — entender features capturadas
3. `docs/dashboard-plan.md` §Fase 3 — plumbing com Streamlit
4. `~/Desktop/AI Interaction Analysis/notebooks/data-profile/_template.qmd`
   — referência principal do padrão (598 linhas, descritivo zero trato)
5. `~/Desktop/AI Interaction Analysis/notebooks/data-profile/web-chat/04-chatgpt.qmd`
   — exemplo de wrapper minimal (61 linhas)
6. `~/Desktop/AI Interaction Analysis/notebooks/data-profile/_style.css`
   — copiar como ponto de partida

**Pra abrir e explorar antes de decidir conteúdo:**
- `data/processed/ChatGPT/*.parquet` (4 arquivos)

---

## 11. Notas finais

### 11.1. Não escrever plan formal antes de explorar

A sessão Quarto é **exploratória por natureza**. Plan especulativo vira
refator depois. Padrão correto: abre parquet → explora → decide → codifica.

Se durante a exploração aparecer algo surpreendente, ajusta o briefing
(este doc) e prossegue.

### 11.2. Entregável da Fase 3.1 é único arquivo

`notebooks/chatgpt.qmd` + `_style.css`. **Não inflar** com outros notebooks
ainda. Cross-plataforma e template parametrizado vêm depois.

### 11.3. Render time importa

Parquets são leves (15M messages é o maior). Mas plotly em browser pode
travar com 10k pontos sem agregação. **Agregar antes de plotar** —
groupby por mês, top N modelos, etc.

### 11.4. Permanência do output

`notebooks/_output/*.html` deve ser **gitignored** (é gerado, não fonte).
`.qmd` é versionado.

---

**Fim do briefing.** Próxima ação da sessão Quarto: abrir os parquets,
explorar 30 min, decidir o que ressoa, escrever `chatgpt.qmd`.
