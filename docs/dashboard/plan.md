# Plan: dashboard Streamlit + Quarto

Plan formal pra construção do dashboard descritivo do projeto. Pensado pra
implementação em sessão paralela à atual.

---

## 1. Contexto e fronteira

Este projeto (`multi-ai-session-data-extractor`) descolou do projeto
`~/Desktop/AI Interaction Analysis/` quando a parte de **coleta** virou
maior que a análise. O escopo aqui é:

```
   ESTE PROJETO (multi-ai-session-data-extractor)
   ├── Captura (extractors)
   ├── Reconciliação (merged)
   ├── Parser → parquet               ← interface universal de saída
   └── Dashboard descritivo simples   ← "olha o que tu tem"
                                        princípio: "zero trato"

   ────────────── parquet ──────────────

   AI INTERACTION ANALYSIS (outro projeto)
   ├── Consome parquet
   ├── Templates de notebook
   ├── Framework qualitativo
   └── Análise interpretativa profunda
```

O dashboard daqui é **catálogo + saúde + volume**. Quem quer interpretação
pesada leva os parquets pra outro projeto.

---

## 2. Princípios

### 2.1. "Zero trato"

O dashboard apresenta dados, não interpreta. Lista do que **NÃO** é objetivo:
- Análise de sentimento
- Clusterização semântica
- Coding qualitativo
- Narrative discovery
- Detecção de tópicos / temas
- Ranking de "qualidade"

O que **É** objetivo:
- Counts e distribuições
- Timeline de atividade
- Tabelas filtráveis e ordenáveis
- Busca por título / texto direto (não semântica)
- Saúde operacional do sistema
- Triggers de captura (botões pra rodar sync)

### 2.2. Audiência expandida

Não é só pro autor — é pra qualquer pessoa que baixe o projeto. Implica:
- Setup TRIVIAL (`pip install + streamlit run`)
- Defaults sensatos (zero config exigida)
- Erros amigáveis ("Você ainda não rodou sync — execute X primeiro")
- Documentação clara que não assume contexto prévio

### 2.3. Interface separada da ação

- **Terminal**: pra debug, dev, primeira vez
- **Dashboard**: pra usuário final, dia-a-dia, ver status e disparar updates

Os dois caminhos coexistem; o dashboard é UX, não esconde o terminal.

---

## 3. Stack

### 3.1. Streamlit (dashboard interativo)

- Python puro, sem JS
- Componentes nativos: tabela, gráfico, botão, spinner, markdown
- Trigger de subprocess via `subprocess.run` (blocking) e `subprocess.Popen` (não-blocking pra render em bg)
- Roda como server local: `streamlit run dashboard.py`

### 3.2. Quarto (descritivo rico)

- Notebooks renderizados em HTML estático
- Por plataforma: `notebooks/<plataforma>.qmd`
- Consome parquets de `data/processed/<plataforma>/`
- Streamlit linka pro HTML rendirizado (abre em aba nova)
- Quem quer adaptar/entender abre o `.qmd` direto e vê o código

### 3.3. Por que essa combinação

| | Streamlit | Quarto |
|---|---|---|
| Propósito | App interativa | Documento reproduzível |
| Trigger de ação | ✅ Sim | ❌ Não |
| Mostra código | ❌ Esconde | ✅ Visível |
| Deploy | Server local | HTML estático |
| Quem usa | Usuário final | Quem quer entender / adaptar |

Streamlit responde "o que tem aqui?". Quarto responde "como esse dado foi
processado?". Complementares, não duplicados.

### 3.4. Dependência: Quarto não é `pip install`

Quarto é binário separado. Documentar instalação:

```bash
# macOS
brew install quarto

# Linux
# baixar release de github.com/quarto-dev/quarto-cli
```

Streamlit detecta se Quarto está instalado:
- Se sim → habilita botões "Ver dados detalhados"
- Se não → mostra mensagem amigável, oculta links

---

## 4. Estrutura de páginas

### 4.1. Overview (página inicial)

```
┌─────────────────────────────────────────────────────────────┐
│  AI Sessions Tracker                                        │
├─────────────────────────────────────────────────────────────┤
│  Total capturado: X.YYY convs across N plataformas          │
│  Última run global: há Xh (Plataforma, data)                │
│  ⚠️ N plataformas atrasadas                                 │
├─────────────────────────────────────────────────────────────┤
│  [🔄 Atualizar todas]                                       │
├─────────────────────────────────────────────────────────────┤
│  Tabela cross-plataforma (1 linha por plataforma)           │
│  Timeline cumulativa (gráfico)                              │
│  Alertas / signals                                          │
└─────────────────────────────────────────────────────────────┘
```

**Tabela cross-plataforma — colunas:**

| Plataforma | Status | Última captura | Última conv mexida no servidor | Total | Active | Preserved | Storage | [Ações] |
|---|---|---|---|---|---|---|---|---|

**Status:**
- 🟢 < 24h sem rodar
- 🟡 1-3 dias
- 🔴 > 3 dias
- ⚫ nunca rodou

### 4.2. Drill-down por plataforma

Click numa plataforma → tela detalhada:

- Status: última run, próxima sugerida, saúde
- Histórico (capture_log.jsonl + reconcile_log.jsonl em tabela)
- Stats agregados (total, projects, sources, archived ratio)
- Lista de preserved_missing (convs que sumiram do servidor)
- Botão "🔄 Sync esta plataforma"
- Botão "📊 Ver dados detalhados" (link pro Quarto rendirizado, se Quarto instalado e parser tiver rodado)

### 4.3. Quarto descritivo (link a partir do drill-down)

Por plataforma, um QMD que consome os parquets:

- Total de convs, msgs, projects, sources
- Timeline de atividade (criação ao longo do tempo)
- Por modelo (default_model_slug)
- Por project (ranking)
- Distribuição de tamanho de conv (count de msgs)
- Voice mode vs text (se aplicável)
- Top conversas mais recentes
- Tabela completa filtrável (DT.js no Quarto)

**Princípio "zero trato" se aplica aqui também:** counts, distribuições,
timelines. Sem interpretação. Sem clustering. Sem sentiment.

---

## 5. Fluxo "Update All"

Sequencial (uma plataforma por vez), com render do Quarto em background.

```python
def update_all(plataformas: list[str]):
    pending_renders = []  # [(plat, subprocess.Popen)]
    
    for plat in plataformas:
        # SYNC bloqueante
        with st.spinner(f"Sync {plat}..."):
            st.warning(f"⚠️ Sync em andamento — não feche esta aba.")
            result = subprocess.run(sync_cmd_for(plat), capture_output=True)
            if result.returncode != 0:
                st.error(f"❌ Sync {plat} falhou: {result.stderr}")
                continue
            st.success(f"✅ Sync {plat} ok")
        
        # RENDER em background (não bloqueia próximo sync)
        if quarto_installed():
            proc = subprocess.Popen(
                ["quarto", "render", f"notebooks/{plat}.qmd"]
            )
            pending_renders.append((plat, proc))
    
    # Espera renders pendentes
    if pending_renders:
        with st.spinner("Finalizando renders..."):
            for plat, proc in pending_renders:
                proc.wait()
                if proc.returncode != 0:
                    st.warning(f"⚠️ Render {plat} falhou — sync ok, mas dashboard descritivo não atualizou")
    
    st.balloons()
```

**Comportamento esperado:**
1. Click "Update All" → fila começa
2. Plataforma 1: warning "não feche", spinner, sync roda, termina
3. Render plataforma 1 dispara em background (não bloqueia)
4. Plataforma 2: começa imediatamente, em paralelo ao render da 1
5. ... etc
6. No fim, espera todos os renders pendentes
7. Confirmação visual

**Estados do link "Ver dados detalhados":**
- Render OK: link clicável, abre HTML em aba nova (`target="_blank"`)
- Render em andamento: spinner inline ("⏳ renderizando...")
- Render falhou: link desabilitado + tooltip explicando
- Quarto não instalado: oculto, mostra hint sobre instalação

---

## 6. Catálogo de métricas (sem parser)

Tudo extraível diretamente de `chatgpt_merged.json`, `_files.json`, e os
`.jsonl` de capture/reconcile. **Não precisa do parser pra montar o
dashboard inicial.**

### 6.1. Stats por plataforma

| Métrica | Como extrair |
|---|---|
| Total convs | `len(merged.conversations)` |
| Active | filtrar `_last_seen_in_server == today` |
| Preserved missing | inverso (não vistas hoje) |
| Convs em projects vs soltas | filtrar por `_project_id != null` |
| Conv mais antiga | `min(create_time)` |
| Conv mais nova (servidor) | `max(update_time)` |
| Total estimado de msgs | `sum(len(mapping))` por conv |
| Convs arquivadas | `_archived == true` |
| Modelos usados | distinct `default_model_slug` |
| Convs por project | groupby `_project_id` |

### 6.2. Stats de projects

| Métrica | Como extrair |
|---|---|
| Total projects | `len(project_sources/g-p-*/)` |
| Projects com sources | `_files.json` não vazio |
| Projects vazios | inverso |
| Total sources | sum cross-projects |
| Sources active vs preserved | filtrar `_preserved_missing` |
| Projects deletados no servidor | todos os files preserved |
| Tamanho total binários | `sum(file.stat().st_size)` |

### 6.3. Operacional

| Métrica | Como extrair |
|---|---|
| Última run | `tail -1 capture_log.jsonl` |
| Frequência média de sync | `diff(run_started_at)` cross-runs |
| Taxa de erro | `sum(errors) / total runs` |
| Drops de discovery | linhas com `total < baseline * 0.8` |
| Reconcile cumulativo | `sum(added)` ao longo do tempo |
| Tempo médio de run | `mean(duration_seconds)` |

### 6.4. Cross-plataforma

| Métrica | Como extrair |
|---|---|
| Total agregado | sum dos mergeds |
| Distribuição por plataforma | % de cada |
| Última sync global | `max(LAST_CAPTURE.run_started_at)` |
| Plataforma mais atrasada | `min(LAST_CAPTURE.run_started_at)` |
| Drops em alguma plataforma | flag se discovery caiu vs baseline |

---

## 7. Fases de implementação

> **Estado atual (2026-05-02):** Fases 1, 2 e 3 entregues. Fase 4 entregue
> pra 5 das 6 plataformas restantes (Claude.ai, Perplexity, Qwen, DeepSeek,
> Gemini); só NotebookLM falta. Este documento permanece como histórico das
> decisões — implementação está cristalizada no código.

### Fase 1: MVP Streamlit (sem parser) — ✅ ENTREGUE

**Entrega:** dashboard rodando com Overview + Drill-down + tabela básica de
convs (apenas metadata, sem mensagens).

**Arquivos novos:**
- `dashboard.py` (entry point)
- `dashboard/` (módulo)
  - `dashboard/data.py` — discovery automática de plataformas em `data/raw/<plat>/` e `data/merged/<plat>/`, leitura dos `LAST_*.md` e `.jsonl`
  - `dashboard/metrics.py` — funções pra extrair métricas (catálogo da seção 6)
  - `dashboard/pages/overview.py` — página inicial
  - `dashboard/pages/platform.py` — drill-down
  - `dashboard/components.py` — componentes reutilizáveis (status badge, tabela, etc)

**`requirements.txt` adicionar:**
- `streamlit>=1.30`
- `plotly>=5.0`

**Critério de pronto:**
- ✅ Roda `streamlit run dashboard.py` sem erro
- ✅ Detecta automaticamente plataformas em `data/`
- ✅ Overview mostra tabela cross-plataforma com status
- ✅ Drill-down mostra histórico + stats da plataforma escolhida
- ✅ Botão "Sync esta plataforma" funciona (bloqueia, mostra output)
- ✅ Botão "Update All" executa fila sequencial
- ✅ Erros são tratados e mostrados de forma amigável
- ✅ README atualizado com seção "Como rodar o dashboard"

---

### Fase 2: Parser ChatGPT (raw → parquet) — ✅ ENTREGUE

**Entrega:** parser Python que transforma `chatgpt_merged.json` em 4 parquets
no schema canônico de `src/schema/models.py`.

**Arquivos novos:**
- `src/parsers/chatgpt.py` — parser principal
- `scripts/chatgpt-parse.py` — CLI wrapper
- `tests/parsers/test_chatgpt.py` — testes
- `data/processed/ChatGPT/{conversations,messages,tool_events,projects}.parquet` (output)

**Lógica chave:**
- Lê `data/merged/ChatGPT/chatgpt_merged.json`
- Pra cada conv, faz tree-walk no `mapping` pra extrair mensagens lineares
- Identifica branches (mensagens com múltiplos children no mapping)
- Extrai tool events (web_search, code_interpreter, etc) das messages
- Salva como parquet preservando schema canônico

**Critério de pronto:**
- ✅ Comando: `python scripts/chatgpt-parse.py` gera os 4 parquets
- ✅ Schema canônico respeitado (testes validam contra `src/schema/models.py`)
- ✅ Idempotente (rodar 2x produz mesmo output)
- ✅ Trata branches (preserva tree, não linealiza com perda)
- ✅ Trata anexos (`attachments` no payload)
- ✅ Tratamento de tool events documentado
- ✅ Testes cobrem: conv simples, conv com branches, conv com tool events, conv com attachments
- ✅ Pyarrow ou fastparquet adicionado ao `requirements.txt`

**Dependências:**
- Requer Pyarrow ou Fastparquet pra escrita parquet
- Adicionar a `requirements.txt`

---

### Fase 3: Quarto descritivo + integração com Streamlit — ✅ ENTREGUE

**Entrega:** notebook QMD do ChatGPT renderizando dashboard descritivo, com
trigger e link a partir do Streamlit.

**Arquivos novos:**
- `notebooks/chatgpt.qmd` — notebook descritivo
- `notebooks/_quarto.yml` — configuração do projeto Quarto
- `notebooks/_styles.scss` — estilos compartilhados (opcional)
- `dashboard/quarto.py` — funções pra detectar Quarto, disparar render, ler estado de render

**Estrutura do `chatgpt.qmd`:**

```markdown
---
title: "ChatGPT — Dados Descritivos"
format: html
---

## Visão Geral
- Total de convs, msgs, projects
- Período coberto

## Atividade ao Longo do Tempo
- Plotly: convs criadas por mês

## Por Modelo
- Tabela: model × count

## Por Projeto
- Top 10 projects por count de convs

## Distribuição de Tamanho
- Histogram: count msgs por conv

## Convs Recentes
- Top 20 mais recentes (data, title, project)

## Tabela Completa
- DataTable filtrável
```

**Integração com Streamlit:**

```python
# dashboard/quarto.py
def quarto_installed() -> bool:
    return shutil.which("quarto") is not None

def render_qmd(plat: str) -> subprocess.Popen:
    return subprocess.Popen(
        ["quarto", "render", f"notebooks/{plat}.qmd"],
        cwd=PROJECT_ROOT,
    )

def html_path(plat: str) -> Path | None:
    p = Path(f"notebooks/_output/{plat}.html")
    return p if p.exists() else None

def is_html_stale(plat: str, parquet_dir: Path) -> bool:
    """HTML é mais antigo que algum parquet? → precisa re-render"""
    html = html_path(plat)
    if html is None:
        return True
    html_mtime = html.stat().st_mtime
    return any(p.stat().st_mtime > html_mtime for p in parquet_dir.glob("*.parquet"))
```

**Botão no Streamlit:**

```python
if quarto_installed():
    if html_path("ChatGPT") and not is_html_stale("ChatGPT", parquet_dir):
        st.markdown(f"[📊 Ver dados detalhados](notebooks/_output/chatgpt.html){{target='_blank'}}")
    elif st.button("📊 Renderizar dados detalhados"):
        with st.spinner("Renderizando..."):
            render_qmd("ChatGPT").wait()
        st.rerun()
else:
    st.info("ℹ️ Instale Quarto pra habilitar visualização detalhada: brew install quarto")
```

**Critério de pronto:**
- ✅ `notebooks/chatgpt.qmd` renderiza com `quarto render`
- ✅ Output em `notebooks/_output/chatgpt.html`
- ✅ Streamlit detecta Quarto instalado, oferece botão
- ✅ Streamlit detecta HTML stale (parquet mais novo) e re-renderiza
- ✅ Streamlit linka pro HTML em nova aba quando disponível
- ✅ Update All executa render em background após sync de cada plataforma
- ✅ Estado visual do link reflete render em andamento / falha / sucesso
- ✅ Documentação de instalação do Quarto no README

---

### Fase 4: Replicar parser + QMD pras outras 6 plataformas — ⚠️ 5/6 ENTREGUES (falta NotebookLM)

Pra cada plataforma (Claude.ai, Gemini, NotebookLM, Qwen, DeepSeek, Perplexity):

1. Parser específico em `src/parsers/<plat>.py` (mesma lógica genérica, adaptações de schema do servidor)
2. Sync orquestrador em `scripts/<plat>-sync.py` (replicar o padrão do ChatGPT-sync de 4 etapas)
3. QMD em `notebooks/<plat>.qmd` (template compartilhado adaptado)

**Critério de pronto:**
- ✅ Cada plataforma tem sync orquestrador funcional
- ✅ Cada plataforma tem parser pra parquet
- ✅ Cada plataforma tem QMD descritivo
- ✅ Dashboard reflete tudo automaticamente (descobre plataformas no filesystem)
- ✅ Update All cobre todas

**Esta fase é grande** — provavelmente subdividida em 6 chunks (um por plataforma).

---

## 8. Setup pra terceiros

### 8.1. README — seção "Como rodar o dashboard"

```markdown
## Dashboard

### Instalação

\```bash
pip install -r requirements.txt
brew install quarto  # opcional, habilita visualização detalhada
\```

### Rodar

\```bash
streamlit run dashboard.py
\```

Abre em `http://localhost:8501`.

### Primeira vez

Se nunca rodou nenhum sync, o dashboard vai mostrar todas as plataformas
como ⚫ (não rodou). Use o botão "Sync esta plataforma" no drill-down de
cada uma. Cada sync abre browser pra login na primeira vez (apenas).

### Update recorrente

Use "🔄 Atualizar todas" no overview. Cada plataforma é atualizada em
sequência. Não feche a aba durante o processo.
```

### 8.2. Detecção de plataformas

Dashboard varre `data/raw/<plat>/` e `data/merged/<plat>/` automaticamente.
Adicionar plataforma nova = nada a configurar no dashboard, basta o sync
escrever os arquivos no padrão esperado.

### 8.3. Detecção de Quarto

Streamlit checa `shutil.which("quarto")`. Se não encontrar, oculta links
e mostra hint de instalação. Não falha o dashboard inteiro por causa disso.

---

## 9. O que NÃO é objetivo

Lista explícita pra evitar scope creep:

- ❌ Análise interpretativa de qualquer tipo (sentiment, clustering, topics)
- ❌ Multi-user (é app local, single-user)
- ❌ Auth / login (não é app web pública)
- ❌ Histórico além do que `.jsonl` já guarda
- ❌ Edição de dados pelo dashboard (read-only do que o sync produziu)
- ❌ Comparação cross-conv ("essa conv parece com aquela")
- ❌ Export pra outros formatos além do parquet (CSV / JSON ad-hoc fica fora)
- ❌ Configurações/preferências persistidas
- ❌ Notificações / alertas push
- ❌ API REST exposta

Se algum desses surgir como necessidade real, é um projeto/extensão separada,
não escopo desse dashboard.

---

## 10. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Streamlit re-run quebra estado durante sync | `st.session_state` pra persistir; subprocess vive fora do Streamlit |
| Quarto não instalado em terceiros | Detecção + fallback amigável; não bloqueia dashboard |
| Render demora muito em parquet grande | Render em background via Popen; Streamlit não bloqueia |
| 2 renders simultâneos degradam máquina fraca | Pra Update All, render fica em fila implícita (próximo sync já demora minutos) |
| Subprocess órfão se user fechar Streamlit no meio | Aceitável; processos OS continuam, terminam sozinhos |
| Pyarrow ausente quebra parsers | Adicionar como dep firme em `requirements.txt` |
| Detecção automática de plataformas falha | Validação na leitura; mensagem clara se algum arquivo está malformado |

---

## 11. Critérios de pronto (geral)

Cada fase tem seus critérios próprios listados acima. Critério geral
"sistema redondo":

- ✅ Setup `pip install + streamlit run` funciona em máquina limpa
- ✅ Dashboard funciona sem erro mesmo sem nenhuma captura ainda feita
- ✅ Updates feitos pela interface refletem na visualização
- ✅ Quarto integration funciona se Quarto instalado, falha graciosa se não
- ✅ Suite de testes existe e passa
- ✅ Documentação no README cobre o ciclo completo

---

## 12. Ordem de implementação sugerida

```
1. Fase 1 (MVP Streamlit) — pode rodar HOJE com dados ChatGPT existentes
   └── Entrega independente, valor imediato

2. Fase 2 (Parser ChatGPT) — desbloqueia Fase 3 e AI Interaction Analysis
   └── Pode ser feita em paralelo à Fase 1 em sessão separada

3. Fase 3 (Quarto + integração) — fecha o ciclo do ChatGPT
   └── Depende de Fase 1 e Fase 2 prontas

4. Fase 4 (outras plataformas) — replica padrão
   └── Cada plataforma é um chunk independente
```

**Independência das fases:**
- Fases 1 e 2 podem ser desenvolvidas em paralelo (uma não depende da outra)
- Fase 3 precisa das duas anteriores
- Fase 4 é repetição do padrão estabelecido nas 3 primeiras

---

## 13. Notas finais

Este plan vai ser executado em sessão paralela à atual. Pra garantir
coerência:

1. **Ler `CLAUDE.md`** antes de começar — princípios do projeto
2. **Ler `docs/glossary.md`** — terminologia
3. **Ler `docs/operations.md`** — como rodar comandos atuais
4. **Não tocar em `src/extractors/` ou `src/reconcilers/`** — código de
   captura está estável e validado, dashboard é layer separado por cima
5. **Commit granular** seguindo `~/.claude/scripts/commit.sh`
6. **Manter testes verdes** a cada commit

Estado atual do projeto (referência):
- ChatGPT: ciclo completo validado (`data/raw/ChatGPT/` + `data/merged/ChatGPT/` populados)
- 1171 convs no merged (1168 active + 3 preserved)
- Outras 6 plataformas: extractors prontos, sync orquestrado pendente
- 100 testes unitários passing
