"""Orchestrator: auth + discovery + fetcher.

NOTA: NotebookLM API NAO expoe sinal confiavel de incremental no discovery.
O campo `update_time` do `wXbhsf` (em nb[5][5]) bumpa periodicamente mesmo
sem mudancas reais no notebook (provavelmente "last indexed" do servidor).
2 fetches consecutivos retornam TUDO IGUAL, mas com gap de ~1h os timestamps
bumpam em todos. Por isso, orchestrator aplica lite-fetch (3 RPCs leves) pra
classificar fetch vs copy contra o estado anterior.

A incrementalidade real fica no reconciler, que compara o conteudo do JSON
(excluindo timestamps voláteis) pra decidir to_use vs to_copy.

--full mantido por compat (no-op atual: ja sempre considera tudo).

PASTA UNICA CUMULATIVA per-account (sem timestamps), espelhando padrao
das outras 6 plataformas. Saida: data/raw/NotebookLM/account-{N}/.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.notebooklm.auth import load_context, ACCOUNT_LANG
from src.extractors.notebooklm.api_client import NotebookLMClient
from src.extractors.notebooklm.batchexecute import load_session
from src.extractors.notebooklm.discovery import discover, persist_discovery
from src.extractors.notebooklm.fetcher import fetch_notebook, lite_fetch_notebook
from src.extractors.notebooklm.refetch_known import refetch_known_notebooklm


BASE_DIR = Path("data/raw/NotebookLM")
# Quando discovery (wXbhsf) cai mais que isso vs maior valor historico, o
# orchestrator nao confia no listing e cai pra refetch_known via UUIDs ja
# salvos no raw cumulativo — caminho que nao depende de discovery.
# Threshold mantido pra evitar falso-fallback (oscilacoes pequenas sao normais).
DISCOVERY_DROP_FALLBACK_THRESHOLD = 0.20
# Alias retro-compat (codigo/testes antigos referenciam pelo nome velho)
DISCOVERY_DROP_ABORT_THRESHOLD = DISCOVERY_DROP_FALLBACK_THRESHOLD


def _account_dir(account: str) -> Path:
    return BASE_DIR / f"account-{account}"


def _resolve_output_dir(account: str) -> Path:
    """Pasta unica cumulativa per-account. Sem timestamps."""
    out = _account_dir(account)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _get_max_known_discovery(output_dir: Path) -> int:
    """Maior count historico em capture_log.jsonl per-account.

    IMPORTANTE: usa output_dir, NAO output_dir.parent — bug preventivo #1
    (em Gemini, counts vazavam entre plataformas via rglob no parent).
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


def _check_discovery_drop(current: int, baseline: int) -> tuple[bool, str | None]:
    """Sinaliza se discovery atual caiu >threshold vs baseline historico.

    Retorna (dropped, reason). Quando dropped=True, o orchestrator cai pra
    refetch_known em vez de abortar (analogo ao ChatGPT desde 2026-05-11).
    """
    if baseline == 0:
        return (False, None)  # primeira run
    drop = (baseline - current) / baseline
    if drop > DISCOVERY_DROP_FALLBACK_THRESHOLD:
        return (
            True,
            f"Discovery parcial: {current} notebooks vs {baseline} no historico "
            f"(queda {drop:.0%}). Threshold={DISCOVERY_DROP_FALLBACK_THRESHOLD:.0%}."
        )
    return (False, None)


def _write_last_capture_md(output_dir: Path, log_entry: dict) -> None:
    """Snapshot human-readable da ultima run."""
    totals = log_entry["totals"]
    md = (
        f"# Last Capture — NotebookLM (account {log_entry['account']})\n\n"
        f"**Run:** {log_entry['started_at']} → {log_entry['finished_at']}\n\n"
        f"## Totals\n\n"
        f"- Notebooks descobertos: {totals.get('notebooks_discovered', 0)}\n"
        f"- Notebooks fetched: {totals.get('notebooks_fetched', 0)}\n"
        f"- Sources fetched: {totals.get('sources_fetched_total', 0)}\n"
        f"- RPCs OK: {totals.get('rpcs_ok_total', 0)}\n"
        f"- RPCs empty: {totals.get('rpcs_empty_total', 0)}\n"
        f"- Notebooks com erros: {totals.get('notebooks_with_errors', 0)}\n"
        f"- Artifacts individuais fetched: {totals.get('artifacts_individual_total', 0)}\n"
        f"- Mind maps fetched: {totals.get('mind_maps_total', 0)}\n"
    )
    (output_dir / "LAST_CAPTURE.md").write_text(md, encoding="utf-8")


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

        # Discovery LAZY — nao persiste ainda
        nbs_all = await discover(client)
        n_discovered = len(nbs_all)

        # Discovery parcial vira fallback automatico pra refetch_known.
        # wXbhsf as vezes retorna paginacao incompleta — em vez de abortar
        # (e marcar notebooks como deletados), cai pra refetch dos UUIDs ja
        # salvos no raw cumulativo. Cada notebook precisa de fetch COMPOSTO
        # (metadata + guide + chat + notes + audios + mind_map + sources),
        # logo reusa o fetch_notebook do fetcher original.
        baseline = _get_max_known_discovery(output_dir)
        dropped, reason = _check_discovery_drop(n_discovered, baseline)
        if dropped:
            print(f"\n{reason} Caindo pra refetch_known via UUIDs salvos.")
            stats = await refetch_known_notebooklm(client, output_dir)
            log_entry = {
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "account": account,
                "hl": ACCOUNT_LANG[account],
                "mode": "refetch_known_fallback",
                "totals": {
                    "notebooks_discovered": stats["total"],
                    "notebooks_fetched": stats["updated"],
                    "notebooks_with_errors": stats["errors"],
                    "sources_fetched_total": 0,
                    "rpcs_ok_total": 0,
                    "rpcs_empty_total": 0,
                    "artifacts_individual_total": 0,
                    "mind_maps_total": 0,
                },
                "errors_sample": [],
            }
            log_path = output_dir / "capture_log.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")
            _write_last_capture_md(output_dir, log_entry)
            print()
            print("=== SUMMARY (refetch_known fallback) ===")
            print(json.dumps(log_entry["totals"], indent=2))
            print(f"\nRaw em: {output_dir}")
            return output_dir

        # Aplica filtros (smoke / only_notebooks) APOS fail-fast
        nbs = nbs_all
        if smoke_limit is not None:
            nbs = nbs[:smoke_limit]
            print(f"SMOKE: limitado a {smoke_limit} notebooks")
        if only_notebooks:
            before = len(nbs)
            nbs = [n for n in nbs if n["uuid"] in only_notebooks]
            missing = only_notebooks - {n["uuid"] for n in nbs}
            print(f"FILTRO --notebook: {len(nbs)}/{before} matchando")
            if missing:
                print(f"  UUIDs nao encontrados na discovery: {missing}")

        # Persist discovery agora — apos fail-fast (bug preventivo #2)
        persist_discovery(nbs_all, output_dir)

        # Detecta raw anterior pra incremental via lite-fetch
        prev_existed = (output_dir / "notebooks").exists() and any(
            (output_dir / "notebooks").glob("*.json")
        )

        if prev_existed and not full and not only_notebooks:
            print(f"\nLite-fetch: comparando 3 RPCs (rLM1Ne+cFji9+gArtLc) por notebook vs estado anterior")
            from src.reconcilers.notebooklm import _eq_lenient
            sem_lite = asyncio.Semaphore(8)

            async def _classify(nb):
                async with sem_lite:
                    lite = await lite_fetch_notebook(client, nb["uuid"])
                prev_path = output_dir / "notebooks" / f"{nb['uuid']}.json"
                if not prev_path.exists():
                    return ("fetch", nb)
                try:
                    prev = json.loads(prev_path.read_text(encoding="utf-8"))
                except Exception:
                    return ("fetch", nb)
                same_meta = _eq_lenient(lite["metadata"], prev.get("metadata"))
                same_notes = _eq_lenient(lite["notes"], prev.get("notes"))
                same_audios = _eq_lenient(lite["audios"], prev.get("audios"))
                if same_meta and same_notes and same_audios:
                    return ("copy", nb)
                return ("fetch", nb)

            classifications = await asyncio.gather(*(_classify(nb) for nb in nbs))
            to_fetch = [nb for action, nb in classifications if action == "fetch"]
            to_copy_nbs = [nb for action, nb in classifications if action == "copy"]
            print(f"  resultado: {len(to_fetch)} fetch, {len(to_copy_nbs)} copy in-place (sem alteracao)")
        else:
            to_fetch = list(nbs)

        print(f"\nFetching {len(to_fetch)} notebooks...")
        all_stats = []
        for i, nb in enumerate(to_fetch):
            s = await fetch_notebook(client, nb["uuid"], nb["title"], output_dir)
            all_stats.append(s)
            marker = "ok" if not s["rpcs_errors"] else f"err={len(s['rpcs_errors'])}"
            print(
                f"  [{i+1}/{len(to_fetch)}] {nb['uuid'][:8]} {nb['title'][:40]!r} "
                f"— {marker}, sources={s['sources_fetched']}/{s['n_source_uuids']}"
            )

        # Log resumo (append-only jsonl)
        log_entry = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "hl": ACCOUNT_LANG[account],
            "smoke_limit": smoke_limit,
            "totals": {
                "notebooks_discovered": n_discovered,
                "notebooks_fetched": len(all_stats),
                "sources_fetched_total": sum(s["sources_fetched"] for s in all_stats),
                "source_uuids_seen": sum(s["n_source_uuids"] for s in all_stats),
                "rpcs_ok_total": sum(s["rpcs_ok"] for s in all_stats),
                "rpcs_empty_total": sum(s["rpcs_empty"] for s in all_stats),
                "notebooks_with_errors": sum(1 for s in all_stats if s["rpcs_errors"]),
                "artifacts_individual_total": sum(s.get("artifacts_fetched_individual", 0) for s in all_stats),
                "mind_maps_total": sum(1 for s in all_stats if s.get("mind_map_fetched")),
            },
            "errors_sample": [s for s in all_stats if s["rpcs_errors"] or s["sources_errors"]][:10],
        }
        log_path = output_dir / "capture_log.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")

        _write_last_capture_md(output_dir, log_entry)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log_entry["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        return output_dir
    finally:
        await context.close()
