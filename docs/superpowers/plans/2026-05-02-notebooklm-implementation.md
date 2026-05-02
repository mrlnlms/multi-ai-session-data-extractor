# NotebookLM Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shipping da 7a/última plataforma (NotebookLM) ao mesmo nível das 6 anteriores: sync orquestrador multi-conta + 8 parquets canônicos+auxiliares + Quarto descritivo + bateria CRUD UI.

**Architecture:** Mirror Gemini (multi-conta `account-1`/`account-2`, pasta única cumulativa, 3-etapa sync). Captura "tudo possível" via `fetch_artifact` (v9rmvd) + `fetch_mind_map_tree` (CYK0Xb) — fechando gaps do orchestrator legacy. 8 parquets: 4 canônicos (Conversation/Message/ToolEvent/Branch) reusando dataclasses existentes + 4 auxiliares específicos (sources/notes/outputs/guide_questions) com 3 dataclasses novos. `guide.summary` vira system message pra garantir `message_count >= 1` (76% dos notebooks tem chat=None no legacy do pai).

**Tech Stack:** Python 3.14, Playwright (headless), batchexecute (Google RPC), pandas/parquet, DuckDB+Plotly+itables (Quarto), pytest.

**Spec:** `docs/superpowers/specs/2026-05-02-notebooklm-schema-design.md`

---

## File Structure

### Modified
- `src/extractors/notebooklm/auth.py` — refactor multi-conta numérica
- `src/extractors/notebooklm/orchestrator.py` — pasta única + bugs preventivos + `fetch_artifact` + `fetch_mind_map_tree`
- `src/extractors/notebooklm/fetcher.py` — adicionar fetch individual de artifacts + mind_map tree
- `src/extractors/notebooklm/discovery.py` — bug preventivo (lazy persist)
- `src/extractors/notebooklm/asset_downloader.py` — multi-conta path
- `src/reconcilers/notebooklm.py` — pasta única per-account, FEATURES_VERSION=2
- `src/parsers/notebooklm.py` — **rewrite total** (legacy outdated)
- `src/schema/models.py` — adicionar 3 dataclasses + helpers `_to_df`
- `scripts/notebooklm-export.py` — nova convenção de account
- `scripts/notebooklm-login.py` — nova convenção de account
- `scripts/notebooklm-reconcile.py` — nova convenção
- `scripts/notebooklm-download-assets.py` — nova convenção
- `notebooks/_style.css` — adicionar cor `#F4B400` se não existir
- `dashboard/data.py` — confirmar `KNOWN_PLATFORMS` lista notebooklm
- `CLAUDE.md` — atualizar tabela de status + bloco "Estado validado"

### Created
- `.storage/notebooklm-profile-1/` (rename de `notebooklm-profile-hello`)
- `.storage/notebooklm-profile-2/` (rename de `notebooklm-profile-marloon`)
- `src/parsers/_notebooklm_helpers.py` — helpers puros do parser
- `scripts/notebooklm-sync.py` — orquestrador 3-etapa multi-conta
- `scripts/notebooklm-parse.py` — CLI parse merged → 8 parquets
- `notebooks/notebooklm.qmd` — Quarto consolidado (multi-conta)
- `notebooks/notebooklm-acc-1.qmd` — Quarto acc-1 only
- `notebooks/notebooklm-acc-2.qmd` — Quarto acc-2 only
- `tests/extractors/notebooklm/` — fixtures + tests pro extractor
- `tests/parsers/test_notebooklm_parser.py` — tests do parser v3
- `docs/notebooklm-server-behavior.md` — comportamento do servidor (CRUD)
- `docs/notebooklm-probe-findings-2026-05-XX.md` — empirical findings
- `docs/notebooklm-parser-validation.md` — paridade vs legacy do pai

### Deleted (após validação)
- `_backup-temp/parser-notebooklm-promocao-2026-05-02/` (após paridade confirmada)

---

## Chunk 1: Multi-conta refactor (auth + profile rename)

**Objetivo:** normalizar profiles e auth pra convenção `account-{1,2}` (alinhada com Gemini). Refactor mínimo, validado por smoke.

**Files:**
- Rename: `.storage/notebooklm-profile-hello/` → `.storage/notebooklm-profile-1/`
- Rename: `.storage/notebooklm-profile-marloon/` → `.storage/notebooklm-profile-2/`
- Modify: `src/extractors/notebooklm/auth.py`
- Modify: `scripts/notebooklm-login.py` (atualizar choices)
- Modify: `scripts/notebooklm-export.py` (atualizar choices)

- [ ] **Step 1: Rename profiles localmente**

```bash
cd /Users/mosx/Desktop/multi-ai-session-data-extractor
mv .storage/notebooklm-profile-hello .storage/notebooklm-profile-1
mv .storage/notebooklm-profile-marloon .storage/notebooklm-profile-2
ls .storage/ | grep notebook
```

Expected: `notebooklm-profile-1` + `notebooklm-profile-2`

- [ ] **Step 2: Refactor `src/extractors/notebooklm/auth.py`**

```python
"""Playwright login persistente pra NotebookLM.

2 contas ativas: account-1 (en, original "hello") e account-2 (pt-BR, original "marloon").
more.design foi perdida (raw antigo preservado no projeto pai).
"""

from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext


VALID_ACCOUNTS = ("1", "2")

# Lang (hl param) por conta — afeta labels em metadata de RPCs (ex: "Deep Dive" vs "Aprofundar").
# Conteudo do user (chat, notes, source text) eh na lingua que foi escrito, independente do hl.
ACCOUNT_LANG = {
    "1": "en",
    "2": "pt-BR",
}


def get_profile_dir(account: str) -> Path:
    if account not in VALID_ACCOUNTS:
        raise ValueError(f"Account invalido: {account!r}. Use um de {VALID_ACCOUNTS}")
    return Path(f".storage/notebooklm-profile-{account}")


async def login(account: str) -> None:
    profile_dir = get_profile_dir(account)
    profile_dir.mkdir(parents=True, exist_ok=True)
    print(f"Abrindo browser (conta {account})...")
    print("Faca login no NotebookLM e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://notebooklm.google.com/", timeout=0)
        await context.wait_for_event("close", timeout=0)

    print(f"Sessao da conta {account} salva em {profile_dir}")


async def load_context(account: str, headless: bool = True) -> BrowserContext:
    profile_dir = get_profile_dir(account)
    if not profile_dir.exists():
        raise RuntimeError(
            f"Profile nao existe: {profile_dir}. "
            f"Rode scripts/notebooklm-login.py --account {account}"
        )
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(profile_dir),
        headless=headless,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
    )
    return context
```

- [ ] **Step 3: Atualizar `scripts/notebooklm-login.py`**

Procurar `choices=list(VALID_ACCOUNTS)` — já consome de auth.py automaticamente. Validar que script ainda parseia args.

- [ ] **Step 4: Atualizar `scripts/notebooklm-export.py`**

Mesmo: já consome `VALID_ACCOUNTS` de auth.py. Validar.

- [ ] **Step 5: Smoke validation**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-export.py --account 1 --smoke 2 2>&1 | tail -15
```

Expected: 2 notebooks fetched OK, sem erros de profile.

- [ ] **Step 6: Run baseline tests**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q 2>&1 | tail -3
```

Expected: 320+ passing, 0 failures.

- [ ] **Step 7: Commit**

```bash
~/.claude/scripts/commit.sh "refactor(notebooklm): multi-conta normalizada — account-1/account-2"
```

---

## Chunk 2: Orchestrator migration (pasta única + bugs preventivos)

**Objetivo:** migrar de `data/raw/NotebookLM Data/<conta>/<timestamp>/` pra `data/raw/NotebookLM/account-{N}/` cumulativo. Aplicar 5 bugs preventivos descobertos em Gemini/Qwen/DeepSeek.

**Files:**
- Modify: `src/extractors/notebooklm/orchestrator.py`
- Modify: `src/extractors/notebooklm/discovery.py` (lazy persist — bug #2)

- [ ] **Step 1: Refactor `discovery.py` pra lazy persist (bug preventivo #2)**

Ler `src/extractors/notebooklm/discovery.py` e identificar onde `discovery_ids.json` é persistido. Separar em 2 funções:
- `discover(client) -> list[dict]` — só descobre, retorna lista, NÃO persiste
- `persist_discovery(nbs, output_dir)` — escreve `discovery_ids.json`

```python
# Antes (exemplo conceitual):
async def discover(client, output_dir):
    nbs = await client.list_notebooks()
    output_dir.mkdir(...)
    (output_dir / "discovery_ids.json").write_text(...)
    return nbs

# Depois:
async def discover(client) -> list[dict]:
    return await client.list_notebooks()

def persist_discovery(nbs: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "discovery_ids.json").write_text(
        json.dumps([{"uuid": n["uuid"], "title": n.get("title", ""),
                     "update_time": n.get("update_time"),
                     "create_time": n.get("create_time")}
                    for n in nbs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 2: Refactor `orchestrator.py` — pasta única**

Substituir `_make_output_dir` (timestamp) por:

```python
BASE_DIR = Path("data/raw/NotebookLM")

def _account_dir(account: str) -> Path:
    return BASE_DIR / f"account-{account}"

def _resolve_output_dir(account: str) -> Path:
    """Pasta unica cumulativa per-account. Sem timestamps."""
    out = _account_dir(account)
    out.mkdir(parents=True, exist_ok=True)
    return out
```

Remover `ACCOUNT_DIR_MAP`, `_make_output_dir`, `_list_raws` (não precisam mais).

- [ ] **Step 3: Adicionar `_get_max_known_discovery` (bug preventivo #1)**

```python
def _get_max_known_discovery(output_dir: Path) -> int:
    """Maior count historico de discovery em capture_log.jsonl per-account.

    IMPORTANTE: usa output_dir, NAO output_dir.parent — bug em Gemini onde
    counts vazavam entre plataformas via rglob.
    """
    log_path = output_dir / "capture_log.jsonl"
    if not log_path.exists():
        return 0
    max_count = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            count = entry.get("totals", {}).get("notebooks_discovered", 0)
            if count > max_count:
                max_count = count
        except Exception:
            continue
    return max_count
```

- [ ] **Step 4: Adicionar fail-fast contra discovery flakey**

```python
DISCOVERY_DROP_ABORT_THRESHOLD = 0.20

def _check_discovery_drop(current: int, baseline: int) -> tuple[bool, str | None]:
    """Aborta se discovery atual cair >20% vs baseline historico."""
    if baseline == 0:
        return (False, None)  # primeira run
    drop = (baseline - current) / baseline
    if drop > DISCOVERY_DROP_ABORT_THRESHOLD:
        return (True,
                f"Discovery caiu {drop:.0%} (atual={current}, baseline={baseline}). "
                f"Threshold={DISCOVERY_DROP_ABORT_THRESHOLD:.0%}. ABORTANDO antes de salvar.")
    return (False, None)
```

- [ ] **Step 5: Refactor `run_export` aplicando lazy persist + fail-fast**

```python
async def run_export(
    account: str,
    full: bool = False,
    smoke_limit: int | None = None,
    only_notebooks: set[str] | None = None,
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = _resolve_output_dir(account)
    print(f"Account: {account} ({ACCOUNT_LANG[account]})")
    print(f"Raw output: {output_dir}")

    context = await load_context(account, headless=True)
    try:
        session = await load_session(context)
        client = NotebookLMClient(context, session, hl=ACCOUNT_LANG[account])

        # Discovery — lazy (não persiste ainda)
        nbs = await discover(client)
        n_discovered = len(nbs)
        print(f"  {n_discovered} notebooks descobertos")

        # Fail-fast
        baseline = _get_max_known_discovery(output_dir)
        aborted, reason = _check_discovery_drop(n_discovered, baseline)
        if aborted:
            print(f"\nFAIL-FAST: {reason}")
            raise RuntimeError(reason)

        if smoke_limit is not None:
            nbs = nbs[:smoke_limit]
            print(f"SMOKE: limitado a {smoke_limit} notebooks")
        if only_notebooks:
            nbs = [n for n in nbs if n["uuid"] in only_notebooks]

        # Persist discovery (após fail-fast — NÃO corrompe baseline)
        persist_discovery(nbs, output_dir)

        # Lite-fetch incremental (lógica existente)
        # ... mantem fluxo atual de classificação fetch/copy ...

        # Fetch + log
        # ... mantem fluxo atual ...

        # Append em capture_log.jsonl (novo — substitui capture_log.json)
        log_entry = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "totals": {
                "notebooks_discovered": n_discovered,
                "notebooks_fetched": len(all_stats),
                # ... resto dos totals
            },
        }
        with open(output_dir / "capture_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        # LAST_CAPTURE.md regenerado
        _write_last_capture_md(output_dir, log_entry)

        return output_dir
    finally:
        await context.close()
```

- [ ] **Step 6: Adicionar `_write_last_capture_md` helper**

```python
def _write_last_capture_md(output_dir: Path, log_entry: dict) -> None:
    """Snapshot human-readable da última run."""
    totals = log_entry["totals"]
    md = f"""# Last Capture — NotebookLM (account {log_entry['account']})

**Run:** {log_entry['started_at']} → {log_entry['finished_at']}

## Totals

- Notebooks descobertos: {totals['notebooks_discovered']}
- Notebooks fetched: {totals['notebooks_fetched']}
- Sources fetched: {totals.get('sources_fetched_total', 0)}
- RPCs OK: {totals.get('rpcs_ok_total', 0)}
- Erros: {totals.get('notebooks_with_errors', 0)}
"""
    (output_dir / "LAST_CAPTURE.md").write_text(md, encoding="utf-8")
```

- [ ] **Step 7: Smoke validation**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-export.py --account 1 --smoke 3
ls data/raw/NotebookLM/account-1/
```

Expected: pasta `data/raw/NotebookLM/account-1/` com `notebooks/`, `sources/`, `discovery_ids.json`, `capture_log.jsonl`, `LAST_CAPTURE.md`.

- [ ] **Step 8: Verify fail-fast funciona (dry test)**

Editar temporariamente `_check_discovery_drop` pra forçar drop. Rodar smoke. Esperar `RuntimeError`. Reverter.

- [ ] **Step 9: Run tests**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 10: Commit**

```bash
~/.claude/scripts/commit.sh "refactor(notebooklm): orchestrator pasta unica per-account + 5 bugs preventivos"
```

---

## Chunk 3: Fetcher gap-fill (fetch_artifact + fetch_mind_map_tree)

**Objetivo:** capturar conteúdo individual dos artifact types 2/4/7/9 (blog/flashcards/quiz/data table/infographic) via v9rmvd e árvore completa do mind map via CYK0Xb. Sem isso, conteúdo dos 5 tipos textuais fica perdido.

**Files:**
- Modify: `src/extractors/notebooklm/fetcher.py`

- [ ] **Step 1: Adicionar helpers de extração de artifact UUIDs e mind_map UUID**

```python
ARTIFACT_TYPES_NEEDING_INDIVIDUAL_FETCH = {2, 4, 7, 9}
# 2=Blog/Report, 4=Flashcards/Quiz, 7=Data Table, 9=Infographic

def _extract_artifact_entries(artifacts_raw) -> list[dict]:
    """Do gArtLc response extrai entries com {uuid, type}.

    Schema empirico: artifacts_raw[0] = list de items
    cada item: [uuid, title, type_int, source_refs, ...]
    """
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        return []
    items = artifacts_raw[0] if isinstance(artifacts_raw[0], list) else []
    out = []
    for it in items:
        if not isinstance(it, list) or len(it) < 3:
            continue
        uid = it[0] if isinstance(it[0], str) else None
        ttype = it[2] if isinstance(it[2], int) else None
        if uid and ttype is not None:
            out.append({"uuid": uid, "type": ttype})
    return out


def _extract_mind_map_uuid(notes_raw) -> str | None:
    """Do cFji9 response extrai UUID do mind map (se houver).

    Schema empirico: notes_raw contem mind_map em alguma posicao —
    descobrir empiricamente quando rodar smoke com mind_map populado.
    """
    if not isinstance(notes_raw, list) or not notes_raw:
        return None
    # Heuristica: procurar UUID em estrutura conhecida
    # TODO: refinar com fixture real de notes raw
    try:
        # Schema posicional — placeholder, refinar empirically
        if len(notes_raw) > 1 and isinstance(notes_raw[1], list):
            for entry in notes_raw[1]:
                if isinstance(entry, list) and entry and isinstance(entry[0], str) and len(entry[0]) == 36:
                    return entry[0]
    except Exception:
        pass
    return None
```

- [ ] **Step 2: Adicionar fetch individual no `fetch_notebook`**

Em `fetcher.py`, após `nb_data` ser montado, adicionar:

```python
    # Salva notebook raw
    with open(nb_dir / f"{nb_uuid}.json", "w", encoding="utf-8") as f:
        json.dump(nb_data, f, ensure_ascii=False)

    # NOVO: fetch individual de artifacts dos tipos 2/4/7/9
    artifacts_dir = nb_dir / f"{nb_uuid}_artifacts"
    artifact_entries = _extract_artifact_entries(nb_data.get("audios"))  # gArtLc raw
    individual_fetched = 0
    for entry in artifact_entries:
        if entry["type"] not in ARTIFACT_TYPES_NEEDING_INDIVIDUAL_FETCH:
            continue
        out = artifacts_dir / f"{entry['uuid']}.json"
        if out.exists():
            continue  # skip-existing
        try:
            content = await client.fetch_artifact(nb_uuid, entry["uuid"])
            if content is not None:
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                payload = {
                    "artifact_uuid": entry["uuid"],
                    "notebook_uuid": nb_uuid,
                    "type": entry["type"],
                    "raw": content,
                }
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                individual_fetched += 1
        except Exception as e:
            stats["rpcs_errors"].append((f"artifact:{entry['uuid'][:8]}", str(e)[:200]))
    stats["artifacts_fetched_individual"] = individual_fetched

    # NOVO: fetch mind_map tree
    mm_uuid = _extract_mind_map_uuid(nb_data.get("notes"))
    if mm_uuid:
        mm_out = nb_dir / f"{nb_uuid}_mind_map_tree.json"
        if not mm_out.exists():
            try:
                tree = await client.fetch_mind_map_tree(nb_uuid, mm_uuid)
                if tree is not None:
                    payload = {
                        "mind_map_uuid": mm_uuid,
                        "notebook_uuid": nb_uuid,
                        "raw": tree,
                    }
                    with open(mm_out, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False)
                    stats["mind_map_fetched"] = True
            except Exception as e:
                stats["rpcs_errors"].append((f"mind_map:{mm_uuid[:8]}", str(e)[:200]))

    # ... resto do fetch_source mantido ...
```

- [ ] **Step 3: Smoke run pra validar captura adicional**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-export.py --account 1 --smoke 5
ls data/raw/NotebookLM/account-1/notebooks/ | head -20
```

Expected: além dos `{uuid}.json`, ver pastas `{uuid}_artifacts/` (pra notebooks com types 2/4/7/9) e arquivos `{uuid}_mind_map_tree.json`.

- [ ] **Step 4: Inspecionar payload pra refinar heurística**

```bash
PYTHONPATH=. .venv/bin/python -c "
import json
from pathlib import Path
art_dir = next(Path('data/raw/NotebookLM/account-1/notebooks').glob('*_artifacts'), None)
if art_dir:
    for p in sorted(art_dir.glob('*.json')):
        d = json.loads(p.read_text())
        print(f'{p.stem[:8]} type={d[\"type\"]}: raw_top_keys/len = {list(d[\"raw\"].keys()) if isinstance(d[\"raw\"], dict) else len(d[\"raw\"])}')
"
```

Documentar schema observado em `docs/notebooklm-probe-findings-2026-05-XX.md` (próximo chunk).

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 6: Commit**

```bash
~/.claude/scripts/commit.sh "feat(notebooklm): captura individual de artifact types 2/4/7/9 + mind_map tree"
```

---

## Chunk 4: Reconciler migration

**Objetivo:** reconciler em pasta única per-account, FEATURES_VERSION=2, preservation completa.

**Files:**
- Modify: `src/reconcilers/notebooklm.py`
- Modify: `scripts/notebooklm-reconcile.py`

- [ ] **Step 1: Ler estado atual do reconciler**

```bash
PYTHONPATH=. .venv/bin/python -c "
import inspect, src.reconcilers.notebooklm as m
print(inspect.getsource(m))" | head -80
```

Mapear: assinatura de `run_reconciliation`, paths atuais, comportamento.

- [ ] **Step 2: Refactor pra multi-conta**

Reconciler precisa:
- Receber `raw_dir: Path` e `merged_dir: Path` (paths absolutos vindos do sync)
- Ler `raw_dir/notebooks/*.json`, `raw_dir/sources/*.json`, `raw_dir/notebooks/*_artifacts/*.json`, `raw_dir/notebooks/*_mind_map_tree.json`
- Escrever `merged_dir/notebooklm_merged.json` + `merged_dir/notebooks/<uuid>.json` + `merged_dir/sources/<uuid>.json` + `merged_dir/artifacts/<uuid>/<artifact_uuid>.json` + `merged_dir/mind_map_trees/<uuid>.json`
- Preservation: notebooks no merged anterior mas ausentes no current viram `_preserved_missing=True`
- `FEATURES_VERSION = 2`

- [ ] **Step 3: Adicionar `LAST_RECONCILE.md` per-account**

Mesmo pattern do orchestrator: snapshot com totals + estados (added/updated/copied/preserved_missing).

- [ ] **Step 4: Adicionar `reconcile_log.jsonl` append-only**

```python
log_entry = {
    "started_at": started_at.isoformat(),
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "account": account,
    "features_version": 2,
    "totals": {
        "added": len(added),
        "updated": len(updated),
        "copied": len(copied),
        "preserved_missing": len(preserved_missing),
        "sources_added": ...,
        "artifacts_added": ...,
    },
}
with open(merged_dir / "reconcile_log.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
```

- [ ] **Step 5: Atualizar `scripts/notebooklm-reconcile.py`**

```python
import argparse
from pathlib import Path

from src.reconcilers.notebooklm import run_reconciliation


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True, choices=["1", "2"])
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()

    raw_dir = Path(f"data/raw/NotebookLM/account-{args.account}")
    merged_dir = Path(f"data/merged/NotebookLM/account-{args.account}")

    report = run_reconciliation(raw_dir, merged_dir, full=args.full)
    if report.aborted:
        raise SystemExit(f"Reconcile abortado: {report.abort_reason}")
    print(f"Reconcile OK: {merged_dir}")
```

- [ ] **Step 6: Smoke run**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-reconcile.py --account 1
ls data/merged/NotebookLM/account-1/
cat data/merged/NotebookLM/account-1/LAST_RECONCILE.md
```

Expected: `notebooks/`, `sources/`, `artifacts/`, `mind_map_trees/`, `notebooklm_merged.json`, `LAST_RECONCILE.md`, `reconcile_log.jsonl`.

- [ ] **Step 7: Run tests**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 8: Commit**

```bash
~/.claude/scripts/commit.sh "refactor(notebooklm): reconciler pasta unica per-account + FEATURES_VERSION=2"
```

---

## Chunk 5: Sync orchestrator (3-etapa)

**Objetivo:** `scripts/notebooklm-sync.py` espelhando `gemini-sync.py` — 3 etapas (capture + assets + reconcile) per-account.

**Files:**
- Create: `scripts/notebooklm-sync.py`
- Modify: `src/extractors/notebooklm/asset_downloader.py` (path multi-conta)

- [ ] **Step 1: Atualizar `asset_downloader.py` pra path multi-conta**

Refactor pra receber `raw_dir: Path` (absoluto) ao invés de `account` + montar path internamente. Manter `assets_manifest.json` por conta dentro do `raw_dir`.

- [ ] **Step 2: Criar `scripts/notebooklm-sync.py`**

```python
"""Sync NotebookLM — captura + assets + reconcile, multi-conta.

Etapas (por conta):
    1. Capture     -> data/raw/NotebookLM/account-{N}/ (cumulativo)
    2. Assets      -> binarios (audio MP4, video MP4, slide PDF+PPTX, source PDFs)
    3. Reconcile   -> data/merged/NotebookLM/account-{N}/

Multi-conta: por default roda ambas (1 e 2). Use --account N pra rodar so uma.

Flags:
    --account {1,2}   roda so a conta indicada (default: ambas)
    --no-binaries     pula etapa 2 (assets)
    --no-reconcile    pula etapa 3
    --full            forca refetch full (propagado pro reconcile — bug #3)
    --smoke N         smoke: N notebooks por conta
    --dry-run

Uso: PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from src.extractors.notebooklm.auth import load_context
from src.extractors.notebooklm.api_client import NotebookLMClient
from src.extractors.notebooklm.batchexecute import load_session
from src.extractors.notebooklm.asset_downloader import download_assets
from src.extractors.notebooklm.orchestrator import BASE_DIR as RAW_BASE, run_export
from src.reconcilers.notebooklm import run_reconciliation


MERGED_BASE = Path("data/merged/NotebookLM")


def _section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


async def _run_assets(raw_dir: Path, account: str) -> dict:
    print("Baixando binarios (audio MP4, video MP4, slide PDF+PPTX, source PDFs)...")
    context = await load_context(account=account, headless=True)
    try:
        session = await load_session(context)
        client = NotebookLMClient(context, session)
        stats = await download_assets(client, raw_dir)
    finally:
        await context.close()

    log_path = raw_dir / "assets_log.json"
    log_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
    print(f"  downloaded={stats['downloaded']} skipped={stats['skipped']} err={len(stats['errors'])}")
    return stats


async def _sync_account(args: argparse.Namespace, account: str) -> int:
    _section(f"ACCOUNT {account}")
    _section(f"Etapa 1/3 — Capture (account {account})")
    try:
        raw_dir = await run_export(account=account, full=args.full, smoke_limit=args.smoke)
    except Exception as e:
        print(f"\nERRO na captura account {account}: {e}")
        return 1
    print(f"\nCapture OK em: {raw_dir}")

    if not args.no_binaries:
        _section(f"Etapa 2/3 — Assets (account {account})")
        try:
            await _run_assets(raw_dir, account=account)
        except Exception as e:
            print(f"\nERRO em assets account {account}: {e}")
            return 1
    else:
        print("\n--no-binaries setado, pulando etapa 2.")

    if args.no_reconcile:
        print("\n--no-reconcile setado, pulando etapa 3.")
        return 0

    _section(f"Etapa 3/3 — Reconcile (account {account})")
    merged_dir = MERGED_BASE / f"account-{account}"
    report = run_reconciliation(raw_dir, merged_dir, full=args.full)
    if report.aborted:
        print(f"  ABORTED: {report.abort_reason}")
        return 2
    print(f"\nMerged em: {merged_dir}")
    return 0


async def main(args: argparse.Namespace) -> int:
    started = time.time()

    if args.dry_run:
        _section("DRY RUN")
        accounts = [args.account] if args.account else ["1", "2"]
        for acc in accounts:
            print(f"  Account {acc}:")
            print(f"    Capture:   data/raw/NotebookLM/account-{acc}/")
            print(f"    Reconcile: data/merged/NotebookLM/account-{acc}/")
        print(f"  Modo:        {'full' if args.full else 'incremental'}")
        print(f"  Etapa 2:     {'skipped' if args.no_binaries else 'run'}")
        print(f"  Etapa 3:     {'skipped' if args.no_reconcile else 'run'}")
        return 0

    accounts = [args.account] if args.account else ["1", "2"]
    overall = 0
    for acc in accounts:
        rc = await _sync_account(args, acc)
        if rc != 0:
            overall = rc

    print()
    print(f"Total elapsed: {time.time() - started:.1f}s")
    return overall


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", choices=["1", "2"], default=None,
                    help="Roda so a conta indicada (default: ambas)")
    ap.add_argument("--no-binaries", action="store_true", help="Pula etapa 2 (assets)")
    ap.add_argument("--no-reconcile", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--smoke", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args)))
```

- [ ] **Step 3: Smoke validation (1 conta, 3 notebooks)**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py --account 1 --smoke 3 2>&1 | tail -30
```

Expected: 3 etapas executam sem erro.

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 5: Commit**

```bash
~/.claude/scripts/commit.sh "feat(notebooklm): sync orquestrador 3-etapa multi-conta"
```

---

## Chunk 6: Full sync run + empirical findings

**Objetivo:** rodar sync completo nas 2 contas, capturar dados reais com chat populado / artifacts / mind_maps. Documentar comportamento descoberto.

**Files:**
- Create: `docs/notebooklm-probe-findings-2026-05-XX.md`

- [ ] **Step 1: Full sync conta 1 (sem smoke)**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py --account 1 2>&1 | tee /tmp/notebooklm-sync-acc1.log
```

Expected: 95+ notebooks descobertos, fetched, reconciled. Pode demorar 10-30min com binários.

- [ ] **Step 2: Full sync conta 2**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py --account 2 2>&1 | tee /tmp/notebooklm-sync-acc2.log
```

- [ ] **Step 3: Inspecionar dados pra findings**

```bash
PYTHONPATH=. .venv/bin/python << 'PYEOF'
import json
from pathlib import Path
from collections import Counter

for acc in ["1", "2"]:
    raw = Path(f"data/raw/NotebookLM/account-{acc}/notebooks")
    if not raw.exists():
        continue
    nbs = list(raw.glob("*.json"))
    nbs = [p for p in nbs if "_mind_map_tree" not in p.name]
    print(f"\n=== Account {acc}: {len(nbs)} notebooks ===")

    has_chat = 0
    artifact_types = Counter()
    has_mind_map = 0
    for p in nbs:
        d = json.loads(p.read_text())
        if d.get("chat") is not None:
            has_chat += 1
        audios = d.get("audios") or []
        if audios and isinstance(audios[0], list):
            for it in audios[0]:
                if isinstance(it, list) and len(it) > 2 and isinstance(it[2], int):
                    artifact_types[it[2]] += 1
        mm_path = p.parent / f"{p.stem}_mind_map_tree.json"
        if mm_path.exists():
            has_mind_map += 1
    print(f"  notebooks com chat: {has_chat}/{len(nbs)}")
    print(f"  artifact types: {dict(artifact_types)}")
    print(f"  notebooks com mind_map tree: {has_mind_map}/{len(nbs)}")
PYEOF
```

- [ ] **Step 4: Inspecionar schema do chat (quando populado)**

```bash
PYTHONPATH=. .venv/bin/python << 'PYEOF'
import json
from pathlib import Path
for p in Path("data/raw/NotebookLM").rglob("notebooks/*.json"):
    if "_mind_map" in p.name or "_artifacts" in str(p):
        continue
    d = json.loads(p.read_text())
    if d.get("chat") is not None:
        print(f"=== Chat populado em {p.parent.parent.name}/{p.stem[:8]} ===")
        print(json.dumps(d["chat"], indent=2, ensure_ascii=False)[:3000])
        break
PYEOF
```

Documentar estrutura observada.

- [ ] **Step 5: Inspecionar schema dos artifacts individuais (v9rmvd)**

```bash
PYTHONPATH=. .venv/bin/python << 'PYEOF'
import json
from pathlib import Path
samples_by_type = {}
for p in Path("data/raw/NotebookLM").rglob("*_artifacts/*.json"):
    d = json.loads(p.read_text())
    t = d["type"]
    if t not in samples_by_type:
        samples_by_type[t] = d
        print(f"\n=== Type {t} sample ({p.parent.parent.name}/{p.stem[:8]}) ===")
        print(json.dumps(d["raw"], indent=2, ensure_ascii=False)[:2000])
PYEOF
```

- [ ] **Step 6: Documentar findings em `docs/notebooklm-probe-findings-2026-05-XX.md`**

Estrutura sugerida:
```markdown
# NotebookLM probe findings — 2026-05-XX

## Volumes
- Account 1: N notebooks, M sources, P artifacts, Q mind_maps
- Account 2: ...

## Chat schema (RPC khqZz)
- N/M notebooks com chat populado
- Schema posicional: chat[0] = ?, chat[1] = ?, chat[2] = list of turns
- Turn structure: ...

## Artifact schemas (RPC v9rmvd)
### Type 2 (Blog/Report)
- Schema: ...
- Conteúdo em raw[X][Y]: markdown text
### Type 4 (Flashcards/Quiz)
- ...
### Type 7 (Data Table)
- ...
### Type 9 (Infographic)
- ...

## Mind map tree schema (RPC CYK0Xb)
- Estrutura: ...

## Comportamento do servidor (placeholder pra Chunk 11)
```

- [ ] **Step 7: Commit findings**

```bash
~/.claude/scripts/commit.sh "docs(notebooklm): empirical findings apos full sync"
```

---

## Chunk 7: Schema models extension

**Objetivo:** adicionar 3 dataclasses novos pras tabelas auxiliares + helpers `_to_df`. Reusar `Conversation`, `Message`, `ToolEvent`, `Branch`, `ProjectDoc` existentes.

**Files:**
- Modify: `src/schema/models.py`
- Test: `tests/schema/test_notebooklm_dataclasses.py` (novo)

- [ ] **Step 1: Write failing test pros 3 dataclasses**

```python
# tests/schema/test_notebooklm_dataclasses.py
import pandas as pd
import pytest

from src.schema.models import (
    NotebookLMNote, notebooklm_notes_to_df,
    NotebookLMOutput, notebooklm_outputs_to_df,
    NotebookLMGuideQuestion, notebooklm_guide_questions_to_df,
)


def test_notebooklm_note_validates_source():
    with pytest.raises(ValueError, match="source"):
        NotebookLMNote(
            note_id="n1", conversation_id="c1", source="invalid",
            account="1", title="t", content="x", kind="note",
            source_refs_json=None, created_at=None,
        )


def test_notebooklm_note_validates_kind():
    with pytest.raises(ValueError, match="kind"):
        NotebookLMNote(
            note_id="n1", conversation_id="c1", source="notebooklm",
            account="1", title="t", content="x", kind="invalid",
            source_refs_json=None, created_at=None,
        )


def test_notebooklm_output_validates_type():
    with pytest.raises(ValueError, match="output_type"):
        NotebookLMOutput(
            output_id="o1", conversation_id="c1", source="notebooklm",
            account="1", output_type=99, output_type_name="invalid",
            title="t", status=None, asset_path=None, content=None,
            source_refs_json=None, created_at=None,
        )


def test_notes_to_df_empty():
    df = notebooklm_notes_to_df([])
    assert isinstance(df, pd.DataFrame)
    assert "note_id" in df.columns


def test_outputs_to_df_with_rows():
    o = NotebookLMOutput(
        output_id="o1", conversation_id="c1", source="notebooklm",
        account="1", output_type=1, output_type_name="audio_overview",
        title="t", status="ARTIFACT_STATUS_READY",
        asset_path=["data/assets/audio.mp4"], content=None,
        source_refs_json='["src1","src2"]', created_at=pd.Timestamp("2026-05-02"),
    )
    df = notebooklm_outputs_to_df([o])
    assert len(df) == 1
    assert df.iloc[0]["output_type"] == 1


def test_guide_question_basic():
    q = NotebookLMGuideQuestion(
        question_id="q1", conversation_id="c1", source="notebooklm",
        account="1", question_text="Qual...", full_prompt="Create a briefing...",
        order=0,
    )
    df = notebooklm_guide_questions_to_df([q])
    assert len(df) == 1
    assert df.iloc[0]["order"] == 0
```

- [ ] **Step 2: Run test — verify FAIL**

```bash
PYTHONPATH=. .venv/bin/pytest tests/schema/test_notebooklm_dataclasses.py -v 2>&1 | tail -15
```

Expected: ImportError ou módulo não encontrado.

- [ ] **Step 3: Adicionar dataclasses em `src/schema/models.py`**

Após `ProjectDoc`, antes de `Branch`:

```python
VALID_NOTE_KINDS = ("note", "brief")

VALID_OUTPUT_TYPES = {
    1: "audio_overview",
    2: "blog_post",
    3: "video_overview",
    4: "flashcards_quiz",
    7: "data_table",
    8: "slide_deck",
    9: "infographic",
    10: "mind_map",
}


@dataclass
class NotebookLMNote:
    note_id: str
    conversation_id: str
    source: str
    account: str
    title: Optional[str]
    content: str
    kind: str  # 'note' | 'brief'
    source_refs_json: Optional[str]
    created_at: Optional[pd.Timestamp]

    def __post_init__(self):
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source '{self.source}' invalido. Validos: {VALID_SOURCES}")
        if self.kind not in VALID_NOTE_KINDS:
            raise ValueError(f"kind '{self.kind}' invalido. Validos: {VALID_NOTE_KINDS}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NotebookLMOutput:
    output_id: str
    conversation_id: str
    source: str
    account: str
    output_type: int
    output_type_name: str
    title: Optional[str]
    status: Optional[str]
    asset_path: Optional[list[str]]
    content: Optional[str]
    source_refs_json: Optional[str]
    created_at: Optional[pd.Timestamp]

    def __post_init__(self):
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source '{self.source}' invalido. Validos: {VALID_SOURCES}")
        if self.output_type not in VALID_OUTPUT_TYPES:
            raise ValueError(
                f"output_type {self.output_type} invalido. "
                f"Validos: {sorted(VALID_OUTPUT_TYPES.keys())}"
            )
        expected_name = VALID_OUTPUT_TYPES[self.output_type]
        if self.output_type_name != expected_name:
            raise ValueError(
                f"output_type_name '{self.output_type_name}' nao bate com "
                f"type {self.output_type} (esperado '{expected_name}')"
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NotebookLMGuideQuestion:
    question_id: str
    conversation_id: str
    source: str
    account: str
    question_text: str
    full_prompt: str
    order: int

    def __post_init__(self):
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source '{self.source}' invalido. Validos: {VALID_SOURCES}")

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Adicionar helpers `_to_df` no fim do arquivo**

```python
def notebooklm_notes_to_df(notes: list[NotebookLMNote]) -> pd.DataFrame:
    cols = [f.name for f in fields(NotebookLMNote)]
    return _models_to_df(notes, cols)


def notebooklm_outputs_to_df(outputs: list[NotebookLMOutput]) -> pd.DataFrame:
    cols = [f.name for f in fields(NotebookLMOutput)]
    return _models_to_df(outputs, cols)


def notebooklm_guide_questions_to_df(qs: list[NotebookLMGuideQuestion]) -> pd.DataFrame:
    cols = [f.name for f in fields(NotebookLMGuideQuestion)]
    return _models_to_df(qs, cols)
```

- [ ] **Step 5: Run test — verify PASS**

```bash
PYTHONPATH=. .venv/bin/pytest tests/schema/test_notebooklm_dataclasses.py -v 2>&1 | tail -10
```

Expected: 6 passed.

- [ ] **Step 6: Run all tests (no regressions)**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q 2>&1 | tail -3
```

Expected: 326+ passed (320 baseline + 6 novos).

- [ ] **Step 7: Commit**

```bash
~/.claude/scripts/commit.sh "feat(schema): adiciona NotebookLMNote/Output/GuideQuestion + helpers"
```

---

## Chunk 8: Parser v3 (rewrite total)

**Objetivo:** `src/parsers/notebooklm.py` rewrite total. Helpers em `_notebooklm_helpers.py`. Lê merged → 8 parquets. Idempotente. TDD com fixtures.

**Files:**
- Backup: `_backup-temp/parser-notebooklm-promocao-2026-05-02/notebooklm.py` (legacy)
- Modify: `src/parsers/notebooklm.py` (rewrite)
- Create: `src/parsers/_notebooklm_helpers.py`
- Create: `tests/parsers/test_notebooklm_parser.py`
- Create: `tests/parsers/fixtures/notebooklm_merged_minimal.json` (sintética)

- [ ] **Step 1: Backup do legacy**

```bash
mkdir -p _backup-temp/parser-notebooklm-promocao-2026-05-02
cp src/parsers/notebooklm.py _backup-temp/parser-notebooklm-promocao-2026-05-02/
```

- [ ] **Step 2: Criar fixture mínima sintética**

`tests/parsers/fixtures/notebooklm_merged_minimal.json`:

```json
{
  "notebooks": [
    {
      "uuid": "nb-uuid-1",
      "title": "Test Notebook",
      "account": "1",
      "create_time": 1735000000,
      "update_time": 1735100000,
      "metadata": [["Test Notebook", [[["src-uuid-1"], "test.pdf", [null, 1000, [1735000000, 0]]]]]],
      "guide": [["Resumo do notebook.", [[["Pergunta 1?", "Prompt completo 1"], ["Pergunta 2?", "Prompt completo 2"]]]]],
      "chat": null,
      "notes": [[[["note-uuid-1", ["note-uuid-1", "Nota teste"], 1, [1735050000, 0]]]]],
      "audios": [[[["art-1", "Audio teste", 1, [], "ARTIFACT_STATUS_READY"], ["art-2", "Blog teste", 2, [], "ARTIFACT_STATUS_READY"]]]],
      "_artifacts_individual": {
        "art-2": {"raw": [["Blog content..."]]}
      },
      "_mind_map_tree": null
    }
  ],
  "sources": {
    "src-uuid-1": {
      "source_uuid": "src-uuid-1",
      "notebook_uuid": "nb-uuid-1",
      "raw": [["test.pdf", "Texto extraido do PDF de teste...", 1000, []]]
    }
  }
}
```

(Schema exato dos posicionais será refinado com fixture real apos empirical findings — esta é placeholder.)

- [ ] **Step 3: Write failing tests pro parser**

```python
# tests/parsers/test_notebooklm_parser.py
import json
from pathlib import Path
import pandas as pd
import pytest

from src.parsers.notebooklm import NotebookLMParser


FIXTURE = Path(__file__).parent / "fixtures" / "notebooklm_merged_minimal.json"


@pytest.fixture
def merged_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parser_generates_8_parquets(merged_data, tmp_path):
    parser = NotebookLMParser()
    out = parser.parse(merged_data, output_dir=tmp_path)
    expected = {
        "notebooklm_conversations.parquet",
        "notebooklm_messages.parquet",
        "notebooklm_tool_events.parquet",
        "notebooklm_branches.parquet",
        "notebooklm_sources.parquet",
        "notebooklm_notes.parquet",
        "notebooklm_outputs.parquet",
        "notebooklm_guide_questions.parquet",
    }
    files = {p.name for p in tmp_path.glob("*.parquet")}
    assert expected.issubset(files)


def test_conversation_per_notebook(merged_data, tmp_path):
    parser = NotebookLMParser()
    parser.parse(merged_data, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_conversations.parquet")
    assert len(df) == len(merged_data["notebooks"])
    assert df.iloc[0]["conversation_id"] == "account-1_nb-uuid-1"
    assert df.iloc[0]["source"] == "notebooklm"
    assert df.iloc[0]["account"] == "1"


def test_guide_summary_becomes_system_message(merged_data, tmp_path):
    parser = NotebookLMParser()
    parser.parse(merged_data, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_messages.parquet")
    assert len(df) >= 1  # pelo menos a system msg
    sys_msgs = df[df["role"] == "system"]
    assert len(sys_msgs) == 1
    assert "Resumo do notebook" in sys_msgs.iloc[0]["content"]


def test_branches_one_per_conv(merged_data, tmp_path):
    parser = NotebookLMParser()
    parser.parse(merged_data, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_branches.parquet")
    assert len(df) == 1
    assert df.iloc[0]["branch_id"] == "account-1_nb-uuid-1_main"
    assert df.iloc[0]["is_active"] == True


def test_outputs_includes_artifact_types(merged_data, tmp_path):
    parser = NotebookLMParser()
    parser.parse(merged_data, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_outputs.parquet")
    types = set(df["output_type"].unique())
    assert 1 in types  # audio
    assert 2 in types  # blog


def test_sources_with_content(merged_data, tmp_path):
    parser = NotebookLMParser()
    parser.parse(merged_data, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_sources.parquet")
    assert len(df) == 1
    assert df.iloc[0]["doc_id"] == "src-uuid-1"
    assert "Texto extraido" in df.iloc[0]["content"]


def test_guide_questions_parsed(merged_data, tmp_path):
    parser = NotebookLMParser()
    parser.parse(merged_data, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_guide_questions.parquet")
    assert len(df) == 2
    assert df.iloc[0]["order"] == 0


def test_idempotent(merged_data, tmp_path):
    parser = NotebookLMParser()
    parser.parse(merged_data, output_dir=tmp_path)
    sizes_first = {p.name: p.stat().st_size for p in tmp_path.glob("*.parquet")}
    parser.parse(merged_data, output_dir=tmp_path)
    sizes_second = {p.name: p.stat().st_size for p in tmp_path.glob("*.parquet")}
    assert sizes_first == sizes_second
```

- [ ] **Step 4: Run tests — verify FAIL**

```bash
PYTHONPATH=. .venv/bin/pytest tests/parsers/test_notebooklm_parser.py -v 2>&1 | tail -15
```

Expected: ImportError ou attribute errors.

- [ ] **Step 5: Implementar `src/parsers/_notebooklm_helpers.py`**

Helpers puros (sem state, fácil de testar):
- `extract_sources_from_metadata(metadata_raw) -> list[dict]` — uuid + filename
- `extract_guide(guide_raw) -> dict` — {summary, questions: [{text, prompt, order}]}
- `extract_chat_turns(chat_raw) -> list[dict]` — placeholder até empirical
- `extract_notes(notes_raw) -> list[dict]`
- `extract_artifacts_list(artifacts_raw) -> list[dict]` — uuid, type, title, status, urls
- `extract_artifact_content(individual_raw, type) -> str | None`
- `extract_mind_map_tree(tree_raw) -> str` — JSON serialized
- `parse_source_content(source_raw) -> str` — texto extraído
- `parse_timestamp(epoch_or_array) -> pd.Timestamp | None`

Cada um com docstring 1-line. Implementação refinada empiricamente após Chunk 6.

- [ ] **Step 6: Implementar `src/parsers/notebooklm.py` (rewrite total)**

```python
"""Parser canonico v3 pra NotebookLM.

Le merged em data/merged/NotebookLM/account-{N}/notebooklm_merged.json
e gera 8 parquets em data/processed/NotebookLM/:
- 4 canonicos (conversations, messages, tool_events, branches)
- 4 auxiliares (sources, notes, outputs, guide_questions)

Schema canonico em src/schema/models.py.
"""

import json
import uuid as uuid_lib
from pathlib import Path
from typing import Optional
import pandas as pd

from src.schema.models import (
    Conversation, Message, ToolEvent, Branch, ProjectDoc,
    NotebookLMNote, NotebookLMOutput, NotebookLMGuideQuestion,
    VALID_OUTPUT_TYPES,
    conversations_to_df, messages_to_df, tool_events_to_df, branches_to_df,
    project_docs_to_df,
    notebooklm_notes_to_df, notebooklm_outputs_to_df, notebooklm_guide_questions_to_df,
)
from src.parsers._notebooklm_helpers import (
    extract_sources_from_metadata, extract_guide, extract_chat_turns,
    extract_notes, extract_artifacts_list, extract_artifact_content,
    extract_mind_map_tree, parse_source_content, parse_timestamp,
)


SOURCE = "notebooklm"


class NotebookLMParser:
    """Parser merged → 8 parquets canonicos+auxiliares."""

    source_name = SOURCE

    def parse(self, merged: dict, output_dir: Path) -> dict:
        """Parse merged dict, escreve 8 parquets em output_dir.

        Retorna stats {table_name: row_count}.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        convs: list[Conversation] = []
        msgs: list[Message] = []
        events: list[ToolEvent] = []
        branches: list[Branch] = []
        sources: list[ProjectDoc] = []
        notes: list[NotebookLMNote] = []
        outputs: list[NotebookLMOutput] = []
        questions: list[NotebookLMGuideQuestion] = []

        sources_raw = merged.get("sources", {})

        for nb in merged.get("notebooks", []):
            self._parse_notebook(
                nb, sources_raw,
                convs, msgs, events, branches,
                sources, notes, outputs, questions,
            )

        # Write parquets (idempotente — overwrite)
        conversations_to_df(convs).to_parquet(
            output_dir / "notebooklm_conversations.parquet", index=False)
        messages_to_df(msgs).to_parquet(
            output_dir / "notebooklm_messages.parquet", index=False)
        tool_events_to_df(events).to_parquet(
            output_dir / "notebooklm_tool_events.parquet", index=False)
        branches_to_df(branches).to_parquet(
            output_dir / "notebooklm_branches.parquet", index=False)
        project_docs_to_df(sources).to_parquet(
            output_dir / "notebooklm_sources.parquet", index=False)
        notebooklm_notes_to_df(notes).to_parquet(
            output_dir / "notebooklm_notes.parquet", index=False)
        notebooklm_outputs_to_df(outputs).to_parquet(
            output_dir / "notebooklm_outputs.parquet", index=False)
        notebooklm_guide_questions_to_df(questions).to_parquet(
            output_dir / "notebooklm_guide_questions.parquet", index=False)

        return {
            "conversations": len(convs),
            "messages": len(msgs),
            "tool_events": len(events),
            "branches": len(branches),
            "sources": len(sources),
            "notes": len(notes),
            "outputs": len(outputs),
            "guide_questions": len(questions),
        }

    def _parse_notebook(self, nb, sources_raw,
                       convs, msgs, events, branches,
                       sources, notes, outputs, questions):
        account = nb.get("account", "1")
        nb_uuid = nb["uuid"]
        conv_id = f"account-{account}_{nb_uuid}"
        created_at = parse_timestamp(nb.get("create_time"))
        updated_at = parse_timestamp(nb.get("update_time"))

        # Guide → summary + questions
        guide = extract_guide(nb.get("guide"))
        summary = guide.get("summary")

        # Sources
        source_entries = extract_sources_from_metadata(nb.get("metadata"))
        for s in source_entries:
            src_raw = sources_raw.get(s["uuid"])
            if src_raw is None:
                continue
            content = parse_source_content(src_raw.get("raw"))
            sources.append(ProjectDoc(
                doc_id=s["uuid"],
                project_id=conv_id,
                source=SOURCE,
                file_name=s["filename"],
                content=content or "",
                content_size=len(content or ""),
                estimated_token_count=(len(content or "") // 4) if content else 0,
                created_at=created_at,
            ))

        # Chat turns + system summary
        chat_turns = extract_chat_turns(nb.get("chat")) or []
        sequence = 0
        if summary:
            msgs.append(Message(
                message_id=f"{conv_id}_guide_summary",
                conversation_id=conv_id,
                source=SOURCE,
                sequence=sequence,
                role="system",
                content=summary,
                model="gemini",
                created_at=created_at,
                account=account,
                branch_id=f"{conv_id}_main",
            ))
            sequence += 1

        for turn in chat_turns:
            msgs.append(Message(
                message_id=turn["id"],
                conversation_id=conv_id,
                source=SOURCE,
                sequence=sequence,
                role=turn["role"],
                content=turn["content"],
                model="gemini",
                created_at=parse_timestamp(turn.get("created_at")),
                account=account,
                branch_id=f"{conv_id}_main",
            ))
            sequence += 1

        # Branch (sempre 1, main)
        if msgs:
            first_id = next((m.message_id for m in msgs if m.conversation_id == conv_id), "")
            last_id = next((m.message_id for m in reversed(msgs) if m.conversation_id == conv_id), first_id)
        else:
            first_id = last_id = ""
        branches.append(Branch(
            branch_id=f"{conv_id}_main",
            conversation_id=conv_id,
            source=SOURCE,
            root_message_id=first_id,
            leaf_message_id=last_id,
            is_active=True,
            created_at=created_at or pd.Timestamp.now(tz="UTC"),
        ))

        # Notes
        for n in extract_notes(nb.get("notes")):
            notes.append(NotebookLMNote(
                note_id=n["uuid"],
                conversation_id=conv_id,
                source=SOURCE,
                account=account,
                title=n.get("title"),
                content=n.get("content", ""),
                kind=n.get("kind", "note"),
                source_refs_json=json.dumps(n.get("source_refs", [])) if n.get("source_refs") else None,
                created_at=parse_timestamp(n.get("created_at")),
            ))

        # Outputs (artifacts + mind_map)
        artifacts_list = extract_artifacts_list(nb.get("audios"))
        individual = nb.get("_artifacts_individual", {})
        for art in artifacts_list:
            t = art["type"]
            if t not in VALID_OUTPUT_TYPES:
                continue
            content = None
            if t in {2, 4, 7, 9} and art["uuid"] in individual:
                content = extract_artifact_content(individual[art["uuid"]].get("raw"), t)
            outputs.append(NotebookLMOutput(
                output_id=art["uuid"],
                conversation_id=conv_id,
                source=SOURCE,
                account=account,
                output_type=t,
                output_type_name=VALID_OUTPUT_TYPES[t],
                title=art.get("title"),
                status=art.get("status"),
                asset_path=art.get("asset_paths"),
                content=content,
                source_refs_json=json.dumps(art.get("source_refs", [])) if art.get("source_refs") else None,
                created_at=parse_timestamp(art.get("created_at")),
            ))

        # Mind map (output type=10)
        mm_raw = nb.get("_mind_map_tree")
        if mm_raw:
            tree_json = extract_mind_map_tree(mm_raw.get("raw"))
            outputs.append(NotebookLMOutput(
                output_id=mm_raw.get("mind_map_uuid", f"{nb_uuid}_mm"),
                conversation_id=conv_id,
                source=SOURCE,
                account=account,
                output_type=10,
                output_type_name="mind_map",
                title=None,
                status=None,
                asset_path=None,
                content=tree_json,
                source_refs_json=None,
                created_at=created_at,
            ))

        # Guide questions
        for i, q in enumerate(guide.get("questions", [])):
            questions.append(NotebookLMGuideQuestion(
                question_id=f"{conv_id}_q{i}",
                conversation_id=conv_id,
                source=SOURCE,
                account=account,
                question_text=q["text"],
                full_prompt=q["prompt"],
                order=i,
            ))

        # Conversation row
        message_count = sum(1 for m in msgs if m.conversation_id == conv_id)
        convs.append(Conversation(
            conversation_id=conv_id,
            source=SOURCE,
            title=nb.get("title"),
            created_at=created_at,
            updated_at=updated_at,
            message_count=message_count,
            model="gemini",
            account=account,
            mode="chat",  # mais proximo dos VALID_MODES atuais
            url=f"https://notebooklm.google.com/notebook/{nb_uuid}",
            summary=summary,
            is_preserved_missing=nb.get("_preserved_missing", False),
            last_seen_in_server=parse_timestamp(nb.get("_last_seen_in_server")),
        ))
```

- [ ] **Step 7: Run tests — verify PASS**

```bash
PYTHONPATH=. .venv/bin/pytest tests/parsers/test_notebooklm_parser.py -v 2>&1 | tail -20
```

Expected: 8 passed.

- [ ] **Step 8: Run all tests (no regressions)**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 9: Commit**

```bash
~/.claude/scripts/commit.sh "feat(parsers): notebooklm parser v3 — rewrite total, 8 parquets canonicos+auxiliares"
```

---

## Chunk 9: CLI parse script + run real

**Objetivo:** `scripts/notebooklm-parse.py` consumindo merged real → 8 parquets em `data/processed/NotebookLM/`. Validar com dados reais das 2 contas.

**Files:**
- Create: `scripts/notebooklm-parse.py`

- [ ] **Step 1: Criar `scripts/notebooklm-parse.py`**

```python
"""Parse merged → 8 parquets canonicos+auxiliares (multi-conta).

Le data/merged/NotebookLM/account-{1,2}/notebooklm_merged.json e
escreve data/processed/NotebookLM/ (8 parquets, agregando ambas contas).

Idempotente — rodar 2x = mesmos bytes.
"""

import json
from pathlib import Path

from src.parsers.notebooklm import NotebookLMParser


MERGED_BASE = Path("data/merged/NotebookLM")
PROCESSED_DIR = Path("data/processed/NotebookLM")


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    merged_combined = {"notebooks": [], "sources": {}}

    for account_dir in sorted(MERGED_BASE.glob("account-*")):
        account = account_dir.name.replace("account-", "")
        merged_path = account_dir / "notebooklm_merged.json"
        if not merged_path.exists():
            print(f"  Skip {account_dir.name} — sem merged JSON")
            continue
        data = json.loads(merged_path.read_text(encoding="utf-8"))
        for nb in data.get("notebooks", []):
            nb["account"] = account
            merged_combined["notebooks"].append(nb)
        merged_combined["sources"].update(data.get("sources", {}))
        print(f"  {account_dir.name}: {len(data.get('notebooks', []))} notebooks")

    parser = NotebookLMParser()
    stats = parser.parse(merged_combined, output_dir=PROCESSED_DIR)
    print()
    print("=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\nParquets em: {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run com dados reais**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-parse.py
ls -la data/processed/NotebookLM/
```

Expected: 8 parquets gerados.

- [ ] **Step 3: Sanity check counts**

```bash
PYTHONPATH=. .venv/bin/python << 'PYEOF'
import pandas as pd
from pathlib import Path
for p in sorted(Path("data/processed/NotebookLM").glob("*.parquet")):
    df = pd.read_parquet(p)
    print(f"{p.name:40} {len(df):>6} rows  cols={len(df.columns)}")
PYEOF
```

Expected: counts coerentes — conversations ~140-200, sources ~1500+, etc.

- [ ] **Step 4: Validation cruzada vs legacy do pai**

```bash
PYTHONPATH=. .venv/bin/python << 'PYEOF'
import pandas as pd
from pathlib import Path

new = Path("data/processed/NotebookLM")
old = Path("/Users/mosx/Desktop/AI Interaction Analysis/data/processed")

for table in ["conversations", "messages", "sources"]:
    p_new = new / f"notebooklm_{table}.parquet"
    p_old = old / f"notebooklm_{table}.parquet"
    if not p_new.exists() or not p_old.exists():
        continue
    n_new = len(pd.read_parquet(p_new))
    n_old = len(pd.read_parquet(p_old))
    delta = n_new - n_old
    sign = "+" if delta >= 0 else ""
    print(f"{table:20} pai={n_old:>6}  v3={n_new:>6}  delta={sign}{delta}")
PYEOF
```

Expected: messages v3 >> messages pai (system summaries adicionadas), sources v3 ≥ sources pai com content extraído.

- [ ] **Step 5: Documentar `docs/notebooklm-parser-validation.md`**

```markdown
# NotebookLM parser v3 — validation cruzada vs legacy do pai

## Counts

| Tabela | Pai (v1) | v3 (novo) | Delta | Notas |
|---|---|---|---|---|
| conversations | 149 | X | +Y | account-N namespace |
| messages | 114 | X | +Y | guide.summary como system |
| sources | 1306 | X | +Y | + content extraido |
| notes | ❌ | X | +X | nova tabela |
| outputs | ❌ | X | +X | 9 tipos |
| ... |

## Conclusao
v3 ⊇ legacy estritamente. Diferencas justificadas.
```

- [ ] **Step 6: Commit**

```bash
~/.claude/scripts/commit.sh "feat(notebooklm): CLI parse + validation cruzada vs legacy pai"
```

---

## Chunk 10: Quarto descritivo (3 documentos)

**Objetivo:** 3 arquivos Quarto seguindo padrão Gemini multi-conta. Cor `#F4B400` (laranja Google).

**Files:**
- Create: `notebooks/notebooklm.qmd` (consolidado, multi-conta)
- Create: `notebooks/notebooklm-acc-1.qmd`
- Create: `notebooks/notebooklm-acc-2.qmd`
- Modify: `notebooks/_style.css` (se cor `#F4B400` precisar entrar)

- [ ] **Step 1: Ler templates Gemini como referência**

```bash
ls notebooks/gemini*.qmd
wc -l notebooks/gemini.qmd notebooks/gemini-acc-1.qmd
```

- [ ] **Step 2: Criar `notebooks/notebooklm-acc-1.qmd`**

Copiar `notebooks/gemini-acc-1.qmd` como base, adaptar:
- Title: "NotebookLM — Account 1 (en)"
- Cor primária inline: `--primary-color: #F4B400`
- Filtro: `WHERE account = '1'`
- Seções (zero trato, descritivo):
  1. Dados disponíveis (8 parquets, contagens)
  2. Cobertura (% notebooks com cada artifact type, com/sem chat, com mind_map)
  3. Volumes (top notebooks por sources, por outputs, por messages)
  4. **9 tipos de outputs** — distribuição + amostras
  5. Sources (volume + extensões + binarios baixados)
  6. Preservation (notebooks com `is_preserved_missing=True`)

- [ ] **Step 3: Criar `notebooks/notebooklm-acc-2.qmd`**

Idêntico ao acc-1 mas filtro `WHERE account = '2'`. Title "NotebookLM — Account 2 (pt-BR)".

- [ ] **Step 4: Criar `notebooks/notebooklm.qmd` (consolidado)**

Adaptar `notebooks/gemini.qmd`:
- Title: "NotebookLM — Consolidado (multi-conta)"
- Stacked bars per-account em seções-chave
- Tabelas com filtro account

- [ ] **Step 5: Render local**

```bash
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm-acc-1.qmd 2>&1 | tail -10
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm-acc-2.qmd 2>&1 | tail -10
QUARTO_PYTHON="$(pwd)/.venv/bin/python" quarto render notebooks/notebooklm.qmd 2>&1 | tail -10
ls -lh notebooks/_output/notebooklm*.html
```

Expected: render < 30s cada, HTML self-contained < 100MB.

- [ ] **Step 6: Validar visual no browser**

```bash
open notebooks/_output/notebooklm.html
```

Confirmar:
- Cor laranja `#F4B400` aparece em headers/links/charts
- Stacked bars mostram per-account
- Tabela de outputs cobre os 9 tipos
- Tudo renderiza sem erro

- [ ] **Step 7: Commit**

```bash
~/.claude/scripts/commit.sh "feat(quarto): notebooklm 3 documentos descritivos (consolidado + per-account)"
```

---

## Chunk 11: Bateria CRUD UI

**Objetivo:** validar comportamento do servidor em rename/delete/pin/sources empiricamente. Documentar em `docs/notebooklm-server-behavior.md`.

**Files:**
- Create: `docs/notebooklm-server-behavior.md`

- [ ] **Step 1: Setup baseline**

Identificar 4 notebooks-cobaia:
- 1 pra rename
- 1 pra delete
- 1 pra pin (se NotebookLM tiver — descobrir na UI)
- 1 pra add/remove source

Documentar UUIDs + estado atual em arquivo temporário `/tmp/notebooklm-crud-baseline.md`.

- [ ] **Step 2: Rename — executar na UI**

User abre notebooklm.google.com (account 1), renomeia 1 notebook (escolher um antigo). Reporta nome novo.

- [ ] **Step 3: Pin — descobrir se NotebookLM tem feature**

User explora UI da account 1 atrás de "pin", "star", "favorite", "fixar". Reporta se existe. Se sim, pina 1 notebook.

- [ ] **Step 4: Add source — adicionar 1 source novo em 1 notebook**

User adiciona 1 PDF/link novo em 1 notebook. Reporta UUID do notebook + nome do source.

- [ ] **Step 5: Delete — deletar 1 notebook**

User deleta 1 notebook (escolher um antigo, sem importância).

- [ ] **Step 6: Run sync de validação**

```bash
PYTHONPATH=. .venv/bin/python scripts/notebooklm-sync.py --account 1 2>&1 | tail -20
PYTHONPATH=. .venv/bin/python scripts/notebooklm-parse.py 2>&1 | tail -10
```

- [ ] **Step 7: Validar resultados**

```bash
PYTHONPATH=. .venv/bin/python << 'PYEOF'
import pandas as pd
df = pd.read_parquet("data/processed/NotebookLM/notebooklm_conversations.parquet")
df = df[df["account"] == "1"]

# Rename
print("Renamed:")
print(df[df["conversation_id"].str.contains("UUID_RENAMED")][["title", "updated_at"]])

# Pin (se aplicavel)
print("\nPinned:")
print(df[df["is_pinned"] == True][["title"]])

# Delete
print("\nPreserved:")
print(df[df["is_preserved_missing"] == True][["title", "last_seen_in_server"]])

# Add source — verificar em sources
src = pd.read_parquet("data/processed/NotebookLM/notebooklm_sources.parquet")
print("\nSources do notebook X:")
print(src[src["project_id"] == "account-1_UUID_NEW_SRC"][["file_name", "content_size"]])
PYEOF
```

- [ ] **Step 8: Documentar `docs/notebooklm-server-behavior.md`**

```markdown
# NotebookLM — comportamento do servidor (validado empiricamente 2026-05-XX)

## Rename
- `update_time` bumpa quando renomeio? (sim/nao)
- Title bate em parquet apos sync? (sim/nao)

## Delete
- Notebook deletado vira `is_preserved_missing=True`? (sim/nao)
- `last_seen_in_server` preservado? (sim/nao)
- Title preservado no merged? (sim/nao)

## Pin/Star
- NotebookLM tem feature de pin? (sim/nao — qual UI?)
- Se sim: capturado? `is_pinned=True` no parquet?
- Se nao: `is_pinned=None` em todas as convs (esperado)

## Add source
- Source novo aparece em parquet? (sim/nao)
- `update_time` do notebook bumpa? (sim/nao)
- Conteudo extraido populado? (sim/nao)

## Remove source
- Source removida vira preserved_missing por source? (descobrir)
- Texto preservado mesmo apos remocao? (sim/nao)

## Generate output novo
- Novo audio/video/blog/etc capturado na proxima sync? (sim/nao)
- `output_type` correto? (sim/nao)

## Delete output
- Comportamento? (descobrir empirically)

## Conclusao
- N/4 cenarios CRUD validados.
- M gaps documentados como TODO upstream-only.
```

- [ ] **Step 9: Commit**

```bash
~/.claude/scripts/commit.sh "docs(notebooklm): bateria CRUD UI + comportamento do servidor"
```

---

## Chunk 12: Review cruzado + CLAUDE.md update + dashboard validation

**Objetivo:** fechar tudo — review cruzado (project-hardening fase 5+6), atualizar CLAUDE.md, confirmar dashboard reflete automaticamente.

**Files:**
- Modify: `CLAUDE.md` (tabela §1 + bloco "Estado validado")
- Modify: `dashboard/data.py` (confirmar `KNOWN_PLATFORMS` se necessário)

- [ ] **Step 1: Confirmar dashboard reflete**

```bash
PYTHONPATH=. streamlit run dashboard/app.py &
# Abrir http://localhost:8501, ver tabela cross-plataforma
```

Confirmar: NotebookLM aparece com 4 status verdes (capture + reconcile + parser + Quarto).

Se algum status falhar:
- Verificar `KNOWN_PLATFORMS` em `dashboard/data.py`
- Verificar `_collect_logs()` agrega `account-*/`
- Verificar `notebooks/notebooklm.qmd` rendiriza pra HTML em `_output/`
- Verificar `dashboard/quarto.py` detecta o HTML

- [ ] **Step 2: Atualizar `CLAUDE.md` — tabela §1**

Mudar linha NotebookLM de `❌ ❌ ❌` pra `✅ ✅ ✅`:

```markdown
| NotebookLM | ✅ | ✅ | ✅ | ✅ | ✅ | shipped 2026-05-XX (X/Y CRUD validados; account-1+account-2; 9 tipos de outputs cobertos) |
```

- [ ] **Step 3: Atualizar `CLAUDE.md` — bloco "Estado validado"**

Adicionar bloco completo após Gemini, com:
- Pasta única + sync 3 etapas
- Cobertura: N notebooks (acc-1) + M (acc-2) / X messages / Y sources / Z outputs
- Reconciler v3 + parser v3 + Quarto
- Comportamento do servidor descoberto
- Bateria CRUD validada
- Comandos

- [ ] **Step 4: Run review cruzado (skill project-hardening fase 5+6)**

```bash
# Invocar skill manualmente — é review, não código
```

Skill verifica:
- Coerência docs vs código
- Naming conventions
- Schema consistency
- Tests cobrem features distintivas
- Bugs preventivos aplicados

Esperado: zero achados.

- [ ] **Step 5: Final test run**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q 2>&1 | tail -3
```

Expected: 320 baseline + N novos = passing.

- [ ] **Step 6: Commit final**

```bash
~/.claude/scripts/commit.sh "docs(notebooklm): SHIPPED — atualiza CLAUDE.md + tabela de status"
```

- [ ] **Step 7: Sugerir arquivamento do plan file (regra global)**

Apos completar plano, sugerir ao user mover este arquivo de `docs/superpowers/plans/` pra `_backup-temp/plans-archive/` (ou onde projeto convencionar) com formato `yyyymmdd-notebooklm-implementation.md`.

---

## Resumo dos critérios de pronto

- [ ] 8 parquets gerados (4 canônicos + 4 auxiliares)
- [ ] Sync 3-etapa idempotente per-account
- [ ] Pasta única `data/raw/NotebookLM/account-{1,2}/`
- [ ] LAST_*.md + jsonls per-account
- [ ] CRUD UI core validado (rename + delete + pin descoberto + sources)
- [ ] Quarto rendiriza < 30s (3 docs)
- [ ] Dashboard 4 status verdes
- [ ] CLAUDE.md atualizado
- [ ] Empirical findings doc
- [ ] Server behavior doc
- [ ] Parser validation doc
- [ ] Tests parser-specific cobrindo 8 parquets
- [ ] Review cruzado: zero achados
- [ ] Suite total >= 320 + N novos
- [ ] CRUD UI 2-3/3+ validado

## Notas finais

- **TDD** rigoroso só no Chunk 8 (parser v3) onde testes valem ouro. Outros chunks usam smoke tests + cross-validation com legacy do pai.
- **Bugs preventivos** aplicados desde Chunk 2 (orchestrator) — não esperar review.
- **Schema posicional** dos artifacts/chat será refinado empiricamente em Chunk 6 antes do parser. Parser usa fixture mínima sintética até lá.
- **Backup do parser legacy** em `_backup-temp/` durante validação. Deletar após paridade confirmada.
- **Cronograma estimado:** ~5 dias de trabalho focado.
