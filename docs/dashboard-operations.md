# Dashboard — operacao

Doc curto pra subir, parar, e acessar o dashboard. Pareado com
`docs/dashboard.md` (manual de funcionalidades) e
`docs/dashboard-plan.md` (plan formal das 4 fases).

---

## 1. Subir

Pre-requisito: venv com deps do `requirements.txt` instaladas. Se nao
tiver:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Comando padrao (foreground, prende o terminal):

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py
```

Roda em <http://localhost:8501> por default. `Ctrl+C` no terminal pra parar.

Em background (libera o shell, log em arquivo):

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py \
  --server.headless true \
  --browser.gatherUsageStats false \
  > /tmp/dashboard.log 2>&1 &
```

Porta diferente (se 8501 ocupada):

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py --server.port 8512
```

---

## 2. Verificar se ja esta rodando

Healthcheck (mais confiavel que abrir browser):

```bash
curl -sf http://localhost:8501/_stcore/health && echo OK
```

Listar processo:

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN
```

---

## 3. Parar

Foreground: `Ctrl+C` no terminal.

Background:

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN | awk 'NR>1 {print $2}' | xargs kill
```

---

## 4. Acessar

| Quem | URL |
|---|---|
| Voce, browser nesta maquina | <http://localhost:8501> |
| Outro device na mesma LAN (celular, outro Mac) | `http://<ip-da-maquina-na-lan>:8501` (Streamlit imprime no boot como "Network URL") |
| Outra sessao Claude com MCP browser | <http://localhost:8501> via `mcp__claude-in-chrome__tabs_create_mcp` |
| Outra sessao Claude sem browser | API `streamlit.testing.v1.AppTest` (programatico) |

**Nao use a "External URL"** que o Streamlit imprime no boot — eh seu IP
publico, expoe o dashboard pra internet sem nenhuma autenticacao. Auth
ficou explicitamente fora de escopo (ver `dashboard-plan.md` secao 9).

---

## 5. Acesso programatico (sem browser)

Outra sessao Claude pode rodar o app sem subir servidor, pra ler estado
ou rodar smoke test:

```python
from streamlit.testing.v1 import AppTest

# overview
at = AppTest.from_file('dashboard.py').run(timeout=30)
print('title:', at.title[0].value)
print('errors:', [str(e) for e in at.error])
print('metrics:', [(m.label, m.value) for m in at.metric])

# drill-down de uma plataforma
at = AppTest.from_file('dashboard.py')
at.session_state['view'] = 'platform'
at.session_state['selected_platform'] = 'ChatGPT'
at.run(timeout=30)
print('metrics:', [(m.label, m.value) for m in at.metric])
print('dataframes:', len(at.dataframe))
```

Util pra:

- Smoke test apos mexer no codigo
- Outra sessao Claude verificar estado atual sem precisar de browser
- CI futura

Warning `missing ScriptRunContext` que aparece eh inocuo (esperado fora do
runtime do Streamlit).

---

## 6. Acesso via Claude-in-Chrome (outra sessao)

Se a outra sessao tem MCP browser:

1. **Garante que o Streamlit esta no ar** (passo 1 acima, ou healthcheck do passo 2).
2. `mcp__claude-in-chrome__tabs_create_mcp(url="http://localhost:8501")`
3. Espera renderizar (Streamlit usa WebSocket — uns 2-3s pra UI montar).
4. `mcp__claude-in-chrome__read_page` pra extrair texto.
5. `mcp__claude-in-chrome__computer` pra clicar em botoes (overview → drill-down, etc).

Pra `mcp__claude-in-chrome__find` ou seletor de DOM, mire em elementos com
`data-testid="stMetricLabel"`, `data-testid="stDataFrame"`, etc — Streamlit
gera IDs estaveis.

---

## 7. Gotchas comuns

| Sintoma | Causa / Fix |
|---|---|
| `ModuleNotFoundError: dashboard` | Faltou `PYTHONPATH=.` antes do `streamlit run` |
| Porta 8501 ocupada (erro no boot) | `--server.port <outra>` ou matar o processo do passo 3 |
| Mudei dado fora do dashboard, UI nao atualiza | Clica "🔁 Recarregar dados" no sidebar (cache de `st.cache_data` so invalida via clear ou via mtime do arquivo) |
| Sync trava com browser do Playwright aberto | Comportamento esperado pro ChatGPT (Cloudflare detecta headless). Espera o subprocess terminar — UI exibe spinner com o nome do comando |
| `use_container_width is deprecated` | Ja foi corrigido pra `width="stretch"`. Se aparecer de novo, eh regressao |
| Tabela de plataformas nao mostra alguma | Discovery automatica varre `data/raw/<plat>/` e `data/merged/<plat>/`. Se a pasta esta vazia, fica como `⚫ nunca rodou`. Se nem isso aparece, conferir nome da plataforma em `KNOWN_PLATFORMS` (`dashboard/data.py`) |

---

## 8. Pra outra sessao do Claude que abra este projeto

Resumo executivo do que precisa saber pra interagir com o dashboard:

1. Subir: `PYTHONPATH=. .venv/bin/streamlit run dashboard.py` (em background se for testar via MCP browser).
2. Healthcheck: `curl -sf http://localhost:8501/_stcore/health`.
3. Acesso: <http://localhost:8501> (mesma maquina) ou via MCP browser.
4. Sem browser: `streamlit.testing.v1.AppTest.from_file('dashboard.py').run()`.
5. Estado e funcionalidades: ler `docs/dashboard.md`.
6. Plano formal e proximas fases: `docs/dashboard-plan.md`.
7. Nao tocar em `src/extractors/` ou `src/reconcilers/` — codigo de captura
   estavel e validado, dashboard e layer separado por cima (regra do
   `dashboard-plan.md` secao 13).
