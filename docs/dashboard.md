# Dashboard — manual de funcionalidades (Fase 1)

Documento vivo do que ja existe no dashboard. Pareado com `dashboard-plan.md`
(o plan formal das 4 fases). Aqui descrevemos so o que esta entregue.

Roda com:

```bash
PYTHONPATH=. streamlit run dashboard.py
```

Abre em <http://localhost:8501>.

---

## 1. Filosofia ("zero trato")

O dashboard apresenta dados, **nao interpreta**. Counts, distribuicoes,
timelines, status. Sem analise de sentimento, clustering semantico, coding
qualitativo, ranking de "qualidade" ou narrative discovery. Quem quer
interpretacao pesada leva os parquets pra `~/Desktop/AI Interaction Analysis/`.

Tambem **read-only**: o dashboard nunca edita os dados que o sync produziu.
Os botoes disparam o sync original via subprocess; nao reescrevem JSONs nem
remergeam por conta propria.

---

## 2. Layout geral

### Sidebar (sempre visivel)

| Elemento | O que faz |
|---|---|
| Titulo "AI Sessions Tracker" | Branding, sem acao |
| Botao "🏠 Overview" | Volta pra pagina inicial (mesmo de "← Voltar" no drill-down) |
| Status do Quarto | Mostra `✅ instalado` ou `➖ ausente (Fase 3)` — apenas informativo na Fase 1, sem efeito visivel |
| Caption sobre logs | Lembra onde os `capture_log.jsonl` e `reconcile_log.jsonl` ficam |
| Botao "🔁 Recarregar dados" | Limpa o `st.cache_data` e re-roda o script. Use depois de rodar sync no terminal pra refletir no dashboard sem reiniciar |

### Roteamento

Single-page, decidido por `st.session_state["view"]`:

- `"overview"` (default) → renderiza `dashboard/pages/overview.py`
- `"platform"` + `selected_platform` → renderiza `dashboard/pages/platform.py`

Trocar de view nao destrui estado dos botoes; o session_state persiste enquanto
a aba do browser estiver aberta.

---

## 3. Pagina Overview

### KPIs cross-plataforma (4 metricas no topo)

| Metric | Origem |
|---|---|
| **Total capturado** | Soma de `total_convs` de todos os mergeds encontrados |
| **Active** | Soma de `active` (visto no servidor hoje) |
| **Preserved missing** | Soma de `preserved_missing` (cumulativo, no merged mas sumiu do servidor) |
| **Plataformas com dados** | Quantas das 7 conhecidas tem alguma captura |

### Linha "Ultima sync global"

Pega a captura mais recente cross-plataforma e mostra `<relativa> (<plat>, <data UTC>)`.
Some se nenhuma plataforma tiver capturas.

### Alertas

- ⚠️ `N plataformas atrasadas` — lista as que estao em status vermelho (>3d sem sync)
- 🚨 `Discovery drop detectado em: ...` — flag quando a discovery mais recente
  caiu mais que 20% vs o maior valor historico (sintoma de `/projects` flaky no ChatGPT)

### Botao "🔄 Atualizar todas"

Sequencial: pra cada plataforma com sync ou export script disponivel, dispara
`subprocess.run(...)` bloqueante, exibe spinner com nome, mostra ✅ ou ❌ no
fim. Limpa o cache no final pra a UI refletir os dados novos.

**Importante:** ChatGPT roda em modo headed por design (Cloudflare detecta
headless). Vai abrir browser do Playwright durante o sync — comportamento
esperado, nao bug. Documentado em `CLAUDE.md` na secao "Headless vs headed
por plataforma".

### Tabela de plataformas

Uma linha por plataforma conhecida (incluindo as que ainda nao rodaram):

| Coluna | Conteudo |
|---|---|
| Status | Badge: 🟢 (<24h) · 🟡 (1-3d) · 🔴 (>3d) · ⚫ (nunca rodou) |
| Plataforma | Nome canonico (ChatGPT, Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity) |
| Ultima captura | Tempo relativo da ultima entrada em `capture_log.jsonl` |
| Ultima conv mexida (servidor) | Placeholder `—` na Fase 1 (precisa abrir merged.json — calculo so feito no drill-down) |
| Total / Active / Preserved | Numeros do merged se existir, `—` caso contrario |

### Botoes de navegacao

Abaixo da tabela, 1 botao por plataforma — clicar muda `view` pra `platform`
e seta `selected_platform`. Equivale a um drill-down direto.

### Timeline de captura

Plotly com `discovery_total` em funcao de `run_started_at`, uma linha por
plataforma com capturas. Vazio mostra mensagem orientativa.

---

## 4. Pagina Drill-down (uma plataforma)

### Header

- Botao "← Voltar" no topo (volta pra overview)
- Titulo `<badge> <Nome>` + caption do status

### Status panel (3 metricas)

| Metric | Conteudo |
|---|---|
| **Ultima captura** | Tempo relativo + caption com data UTC absoluta |
| **Ultimo reconcile** | Tempo relativo + caption com data UTC absoluta |
| **Storage local** | Soma `data/raw/<plat>/` + `data/merged/<plat>/`, com breakdown na caption |

Acima dele: alerta vermelho 🚨 se houver discovery drop nos logs.

### Botao de sync

Pra cada plataforma:

- Se existe `<plat>-sync.py` (so ChatGPT hoje): label `🔄 Sync <Nome>`, roda
  `chatgpt-sync.py --no-voice-pass` (ou equivalente)
- Se so existe `<plat>-export.py` (Claude.ai, Gemini, NotebookLM, Qwen,
  DeepSeek, Perplexity): label `🔄 Export <Nome> (sem orquestrador ainda)`,
  roda o export standalone
- Sem nenhum dos dois: caption explicando que falta script

Comportamento na execucao:

1. `st.spinner` com o comando final visivel (ex: "Rodando chatgpt-sync.py --no-voice-pass...")
2. Bloqueante (subprocess.run com capture_output)
3. Sucesso (`returncode == 0`): `✅ Sync concluido` + expander "stdout" com as
   ultimas 3000 chars + cache clear + rerun pra refletir os dados
4. Falha (`returncode != 0`): `❌ Falhou (exit N)` + expander "stderr" com
   tudo que veio
5. Excecao: `❌ <mensagem>` direto

### Conteudo capturado (so se houver merged.json)

Le o `<plat>_merged.json` cacheado (chave = path + mtime).

Metricas em 3 linhas de cards:

1. Total convs · Active · Preserved missing · Archived
2. Em projects · Standalone · Distinct projects
3. Conv mais antiga · Atividade mais recente

E uma metric solta: Mensagens estimadas (count de nodes com `message`
nao-nulo no `mapping` cumulativo).

### Grafico de criacao por mes

Bar chart Plotly com a contagem de convs criadas por mes (chave `YYYY-MM`).
Util pra ver curva de adocao ao longo do tempo.

### Expanders

Tres listas detalhadas, todas escondidas por default pra nao poluir:

- **Modelos usados (top 10)** — extrai `metadata.model_slug` ou
  `metadata.default_model_slug` de cada message no mapping. Nao tem 1:1 com
  count de convs (uma conv pode usar varios modelos)
- **Top projects por convs** — agrega por `_project_id`, mostra nome quando
  conhecido (`_project_name`)
- **Convs preservadas (deletadas no servidor)** — lista todas as convs cujo
  `_last_seen_in_server` nao bate com a data atual

### Project sources (so se houver pasta no raw)

Bloco com 4+3 metricas sobre `data/raw/<plat>/project_sources/`:

- Projects · Com files · Vazios · Tamanho total
- Files active · Files preserved · Projects 100% preserved

Detecta `_preserved_missing: true` em entradas do `_files.json` pra contar
preservation.

### Historico (tabs)

Tabs "Capturas" e "Reconciles" com tabelas montadas dos `.jsonl`:

| Capturas | Reconciles |
|---|---|
| Inicio · Duracao · Discovery · Fetch ok · Erros | Quando · Added · Updated · Copied · Preserved missing · Warnings |

Mais novas no topo.

---

## 5. Caches e invalidacao

Pra nao reler 119MB de `chatgpt_merged.json` a cada interacao:

```python
@st.cache_data(show_spinner=False)
def _cached_merged_stats(merged_path_str: str, mtime: float):
    return compute_merged_stats(Path(merged_path_str))
```

A chave de cache inclui o `mtime` do arquivo: se o sync regravar o merged,
o mtime muda e o cache invalida automaticamente.

Manualmente:

- Botao "🔁 Recarregar dados" no sidebar
- Apos cada sync iniciado pelo dashboard (cache.clear automatico)

---

## 6. Discovery automatica de plataformas

`dashboard/data.py` declara:

```python
KNOWN_PLATFORMS = ["ChatGPT", "Claude.ai", "Gemini", "NotebookLM",
                   "Qwen", "DeepSeek", "Perplexity"]
```

Mas tambem varre `data/raw/` e `data/merged/`. A lista final eh
`KNOWN_PLATFORMS + extras encontrados em disco`. Resultado:

- Plataformas conhecidas aparecem mesmo sem captura (status ⚫)
- Pasta nova em disco aparece automaticamente, sem mexer no codigo

---

## 7. Erros e mensagens amigaveis

| Situacao | O que mostra |
|---|---|
| Plataforma sem captura | `Nenhuma captura encontrada para <plat>. Use o botao abaixo para rodar a primeira sync.` |
| Plataforma sem script | `Nenhum script de sync ou export para <plat> ainda. Implementar scripts/<plat>-sync.py libera o botao.` |
| Sync falhou | Codigo de saida + expander stderr |
| Excecao no subprocess | Mensagem da excecao direto |
| Discovery drop | Banner vermelho explicando o threshold de 20% |
| Sem merged.json | Caption "Nenhum merged.json encontrado para esta plataforma." |
| Quarto ausente | No sidebar: `➖ ausente (Fase 3)` (sem efeito na Fase 1) |

---

## 8. O que ainda **nao** existe (entra nas fases seguintes)

Pra evitar surpresa:

- **Parser** (Fase 2): nada de parquet ainda. As metricas de mensagens sao
  estimativas leves direto do `mapping` em JSON. Tabela completa filtravel
  com busca por titulo/texto entra na Fase 2/3.
- **Quarto** (Fase 3): botao "Ver dados detalhados" nao existe ainda. O
  sidebar so reporta presenca do binario.
- **Outras plataformas** (Fase 4): so ChatGPT tem sync orquestrador. As
  outras 6 caem no fallback de export individual ate cada uma ganhar seu
  proprio `<plat>-sync.py`.
- **Modelos por conv**: hoje contamos `model_slug` por mensagem (granularidade
  fina). Modelo "default da conversa" precisa do parser.
- **Projects deletados inteiros** (cross-source): drill-down ja mostra
  "Projects 100% preserved" em project_sources, mas nao tem visualizacao
  cruzada de chats orfaos de projects deletados.

---

## 9. Arquivos relevantes

```
dashboard.py                       # entry point
dashboard/
├── __init__.py
├── data.py                        # discovery + leitura de logs/JSON
├── metrics.py                     # extracao de metricas (catalogo sec 6 do plan)
├── components.py                  # status badge, formatacao de tempo/tamanho
├── sync.py                        # subprocess wrapper, deteccao de scripts
└── pages/
    ├── overview.py
    └── platform.py
```

`docs/dashboard-plan.md` — plan formal das 4 fases (este doc cobre so a 1).

`README.md` — secao "Dashboard (Fase 1)" com instalacao e comandos basicos.
