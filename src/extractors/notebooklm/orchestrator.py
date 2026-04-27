"""Orchestrator: auth + discovery + fetcher.

NOTA: NotebookLM API NAO expoe sinal confiavel de incremental no discovery.
O campo `update_time` do `wXbhsf` (em nb[5][5]) bumpa periodicamente mesmo
sem mudancas reais no notebook (provavelmente "last indexed" do servidor).
2 fetches consecutivos retornam TUDO IGUAL, mas com gap de ~1h os timestamps
bumpam em todos. Por isso, orchestrator SEMPRE refetcha tudo (~2-3min).

A incrementalidade real fica no reconciler, que compara o conteudo do JSON
(excluindo timestamps voláteis) pra decidir to_use vs to_copy. Pos-merge, o
download_assets reusa via --copy-from-prev. Resultado pratico: re-fetch e
relativamente barato e o storage economiza via cópia.

--full mantido por compat (no-op atual: ja sempre refetcha).
"""

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.notebooklm.auth import load_context, ACCOUNT_LANG
from src.extractors.notebooklm.api_client import NotebookLMClient
from src.extractors.notebooklm.batchexecute import load_session
from src.extractors.notebooklm.discovery import discover
from src.extractors.notebooklm.fetcher import fetch_notebook, lite_fetch_notebook


ACCOUNT_DIR_MAP = {
    "hello": "hello.marlonlemes",
    "marloon": "marloonlemes",
}


def _account_dir(account: str) -> Path:
    return Path("data/raw/NotebookLM Data") / ACCOUNT_DIR_MAP[account]


def _make_output_dir(account: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
    return _account_dir(account) / ts


def _list_raws(account: str) -> list[Path]:
    base = _account_dir(account)
    if not base.exists():
        return []
    return sorted(
        [p for p in base.iterdir() if p.is_dir() and len(p.name) == 16 and "T" in p.name],
        key=lambda p: p.stat().st_mtime,
    )


def _load_prev_discovery(prev_raw: Path) -> dict[str, dict]:
    p = prev_raw / "discovery_ids.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {e["uuid"]: e for e in data if isinstance(e, dict) and e.get("uuid")}
    except Exception:
        return {}


def _copy_notebook_and_sources(prev_raw: Path, target: Path, uuid: str) -> tuple[bool, int]:
    """Copia notebooks/<uuid>.json + sources referenciados pro target.

    Retorna (notebook_copied, sources_copied).
    """
    src_nb = prev_raw / "notebooks" / f"{uuid}.json"
    dst_nb = target / "notebooks" / f"{uuid}.json"
    dst_nb.parent.mkdir(parents=True, exist_ok=True)
    if not src_nb.exists():
        return (False, 0)
    shutil.copy2(src_nb, dst_nb)

    # Sources referenciados (metadata[0][1])
    n_src = 0
    try:
        nb = json.loads(src_nb.read_text(encoding="utf-8"))
        meta = nb.get("metadata")
        if meta and isinstance(meta, list) and meta and isinstance(meta[0], list):
            src_list = meta[0][1] if len(meta[0]) > 1 else None
            if isinstance(src_list, list):
                for entry in src_list:
                    if isinstance(entry, list) and entry and isinstance(entry[0], list) and entry[0]:
                        suid = entry[0][0]
                        if isinstance(suid, str):
                            ssrc = prev_raw / "sources" / f"{suid}.json"
                            sdst = target / "sources" / f"{suid}.json"
                            if ssrc.exists() and not sdst.exists():
                                sdst.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(ssrc, sdst)
                                n_src += 1
    except Exception:
        pass
    return (True, n_src)


async def run_export(
    account: str,
    full: bool = False,
    smoke_limit: int | None = None,
    only_notebooks: set[str] | None = None,
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = _make_output_dir(account)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Account: {account} ({ACCOUNT_LANG[account]})")
    print(f"Raw output: {output_dir}")

    context = await load_context(account, headless=True)
    try:
        session = await load_session(context)
        client = NotebookLMClient(context, session, hl=ACCOUNT_LANG[account])

        # Discovery
        nbs = await discover(client, output_dir)
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

        # Detecta raw anterior pra incremental via lite-fetch
        prev_raw = None
        if not full and not only_notebooks:
            raws = _list_raws(account)
            cands = [r for r in raws if r != output_dir]
            if cands:
                prev_raw = cands[-1]

        if prev_raw:
            print(f"\nLite-fetch: comparando 3 RPCs (rLM1Ne+cFji9+gArtLc) por notebook vs {prev_raw.name}")
            from src.reconcilers.notebooklm import _eq_lenient
            sem_lite = asyncio.Semaphore(8)

            async def _classify(nb):
                async with sem_lite:
                    lite = await lite_fetch_notebook(client, nb["uuid"])
                # Compara com raw anterior se existe
                prev_path = prev_raw / "notebooks" / f"{nb['uuid']}.json"
                if not prev_path.exists():
                    return ("fetch", nb)
                try:
                    prev = json.loads(prev_path.read_text(encoding="utf-8"))
                except Exception:
                    return ("fetch", nb)
                # Se 3 campos baterem (lenient), copy. Senão, fetch
                same_meta = _eq_lenient(lite["metadata"], prev.get("metadata"))
                same_notes = _eq_lenient(lite["notes"], prev.get("notes"))
                same_audios = _eq_lenient(lite["audios"], prev.get("audios"))
                if same_meta and same_notes and same_audios:
                    return ("copy", nb)
                return ("fetch", nb)

            classifications = await asyncio.gather(*(_classify(nb) for nb in nbs))
            to_fetch = [nb for action, nb in classifications if action == "fetch"]
            to_copy_nbs = [nb for action, nb in classifications if action == "copy"]
            print(f"  resultado: {len(to_fetch)} fetch, {len(to_copy_nbs)} copy do anterior")

            # Copy notebooks unchanged + sources do raw anterior
            for nb in to_copy_nbs:
                _copy_notebook_and_sources(prev_raw, output_dir, nb["uuid"])
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

        # Log resumo
        log = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "hl": ACCOUNT_LANG[account],
            "smoke_limit": smoke_limit,
            "totals": {
                "notebooks_discovered": len(nbs),
                "notebooks_fetched": len(all_stats),
                "sources_fetched_total": sum(s["sources_fetched"] for s in all_stats),
                "source_uuids_seen": sum(s["n_source_uuids"] for s in all_stats),
                "rpcs_ok_total": sum(s["rpcs_ok"] for s in all_stats),
                "rpcs_empty_total": sum(s["rpcs_empty"] for s in all_stats),
                "notebooks_with_errors": sum(1 for s in all_stats if s["rpcs_errors"]),
            },
            "errors_sample": [s for s in all_stats if s["rpcs_errors"] or s["sources_errors"]][:10],
        }
        with open(output_dir / "capture_log.json", "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        print(f"Proximo passo: python scripts/notebooklm-download-assets.py --account {account}")
        return output_dir
    finally:
        await context.close()
