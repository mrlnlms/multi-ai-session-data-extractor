"""Orchestrator Grok: pasta unica cumulativa em data/raw/Grok/.

Padrao alinhado com Qwen/DeepSeek/Gemini. Conversations + workspaces
cumulativos no mesmo path. Modo default: incremental — re-fetcha so
convs com modifyTime > o que ja temos em disco.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.grok.auth import load_context
from src.extractors.grok.api_client import GrokAPIClient
from src.extractors.grok.discovery import (
    discover,
    discover_assets,
    discover_scheduled_tasks,
    persist_discovery,
)
from src.extractors.grok.fetcher import fetch_conversations
from src.extractors.grok.refetch_known import refetch_known_grok


BASE_DIR = Path("data/raw/Grok")

logger = logging.getLogger(__name__)


# Quando discovery cai mais que isso vs maior valor historico, o orchestrator
# nao confia no listing e cai pra refetch_known (caminho que nao depende de
# discovery — refetcha cada conv pelos IDs ja salvos no raw cumulativo).
# Threshold mantido pra evitar falso-fallback (oscilacoes pequenas sao normais).
DISCOVERY_DROP_FALLBACK_THRESHOLD = 0.20
# Alias retro-compat (codigo/testes antigos referenciam pelo nome velho)
DISCOVERY_DROP_ABORT_THRESHOLD = DISCOVERY_DROP_FALLBACK_THRESHOLD


def _get_max_known_discovery(raw_root: Path) -> int:
    """Maior conversations_discovered ja visto em qualquer capture_log."""
    if not raw_root.exists():
        return 0
    max_count = 0
    for log_path in raw_root.rglob("capture_log.jsonl"):
        try:
            with open(log_path) as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    count = (data.get("totals") or {}).get("conversations_discovered", 0)
                    if count > max_count:
                        max_count = count
        except Exception:
            continue
    for log_path in raw_root.rglob("capture_log.json"):
        try:
            with open(log_path) as f:
                data = json.load(f)
            count = (data.get("totals") or {}).get("conversations_discovered", 0)
            if count > max_count:
                max_count = count
        except Exception:
            continue
    return max_count


def _existing_disc_map(raw_dir: Path) -> dict[str, str]:
    """Le discovery_ids.json existente -> {conversationId: modifyTime}."""
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    try:
        data = json.loads(disc.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        c["conversationId"]: c.get("modifyTime") or ""
        for c in data
        if c.get("conversationId")
    }


def _write_last_capture_md(output_dir: Path, log: dict) -> None:
    totals = log.get("totals", {})
    md = (
        "# Last capture\n\n"
        f"- **Quando:** {log.get('finished_at')}\n"
        f"- **Modo:** {log.get('mode')}\n"
        f"- **Conversations:** {totals.get('conversations_discovered', 0)} discovered, "
        f"{totals.get('conversations_fetched', 0)} fetched, "
        f"{totals.get('conversations_reused_incremental', 0)} reused\n"
        f"- **Workspaces:** {totals.get('workspaces_discovered', 0)}\n"
        f"- **Errors:** convs={totals.get('conversations_errors', 0)}\n\n"
        "Ver `capture_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_CAPTURE.md").write_text(md, encoding="utf-8")


async def run_export(
    full: bool = False,
    smoke_limit: int | None = None,
    account: str = "default",
    headless: bool = True,
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = BASE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    prev_map = {} if full else _existing_disc_map(output_dir)
    if prev_map and not full:
        print(f"Modo incremental: {len(prev_map)} convs no estado anterior")
    else:
        print("Modo full")

    context = await load_context(account=account, headless=headless)
    try:
        page = await context.new_page()
        client = GrokAPIClient(context, page)
        await client.warmup()

        convs, workspaces = await discover(client)
        assets = await discover_assets(client)
        tasks = await discover_scheduled_tasks(client)

        # Discovery parcial vira fallback automatico pra refetch_known.
        # Listing /rest/app-chat/conversations as vezes retorna paginacao incompleta —
        # em vez de confiar nesse listing reduzido (e marcar centenas como deletadas),
        # cai pra refetch_known usando os IDs ja salvos no raw cumulativo.
        baseline = _get_max_known_discovery(output_dir)
        curr = len(convs)
        if baseline > 0:
            drop = (baseline - curr) / baseline
            if drop > DISCOVERY_DROP_FALLBACK_THRESHOLD:
                logger.warning(
                    f"Discovery parcial: {curr} convs vs {baseline} no historico "
                    f"(queda {drop:.0%}). Caindo pra refetch_known."
                )
                stats = await refetch_known_grok(client, output_dir)
                # Assets + scheduled tasks ainda valem (independentes do listing)
                (output_dir / "assets.json").write_text(
                    json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                (output_dir / "tasks.json").write_text(
                    json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                log = {
                    "started_at": started_at.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "refetch_known_fallback",
                    "smoke_limit": smoke_limit,
                    "totals": {
                        "conversations_discovered": stats["total"],
                        "conversations_fetched": stats["updated"],
                        "conversations_reused_incremental": 0,
                        "conversations_errors": stats["errors"],
                        "workspaces_discovered": len(workspaces),
                        "assets_discovered": len(assets),
                        "scheduled_tasks_active": len(tasks.get("active") or []),
                        "scheduled_tasks_inactive": len(tasks.get("inactive") or []),
                    },
                    "errors": {"conversations": []},
                }
                log_jsonl = output_dir / "capture_log.jsonl"
                with open(log_jsonl, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log, ensure_ascii=False) + "\n")
                _write_last_capture_md(output_dir, log)
                print()
                print("=== SUMMARY (refetch_known_fallback) ===")
                print(json.dumps(log["totals"], indent=2))
                print(f"\nRaw em: {output_dir}")
                return output_dir
            print(f"Discovery OK: {curr} convs (baseline historico: {baseline})")

        persist_discovery(convs, workspaces, output_dir)
        # Assets globais + scheduled tasks (independente das convs)
        (output_dir / "assets.json").write_text(
            json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "tasks.json").write_text(
            json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        today = started_at.strftime("%Y-%m-%d")
        conv_dir = output_dir / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)

        # Cutoff: re-fetcha so convs com modifyTime novo
        to_fetch: list[str] = []
        reused = 0
        for c in convs:
            cid = c.get("conversationId")
            if not cid:
                continue
            curr_upd = c.get("modifyTime") or ""
            prev_upd = prev_map.get(cid, "")
            existing = conv_dir / f"{cid}.json"
            if cid in prev_map and prev_upd == curr_upd and existing.exists():
                try:
                    obj = json.loads(existing.read_text(encoding="utf-8"))
                    obj["_last_seen_in_server"] = today
                    existing.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                    reused += 1
                    continue
                except Exception:
                    pass
            to_fetch.append(cid)

        if smoke_limit is not None:
            to_fetch = to_fetch[:smoke_limit]
            print(f"SMOKE: limitado a {smoke_limit} convs")

        print(f"Fetching {len(to_fetch)} convs ({reused} reusadas)")
        ok, skipped, errs = await fetch_conversations(
            client, to_fetch, output_dir, skip_existing=False
        )

        for cid in to_fetch:
            f = conv_dir / f"{cid}.json"
            if f.exists():
                try:
                    obj = json.loads(f.read_text(encoding="utf-8"))
                    obj["_last_seen_in_server"] = today
                    f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass

        log = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "full" if full else "incremental",
            "smoke_limit": smoke_limit,
            "totals": {
                "conversations_discovered": len(convs),
                "conversations_fetched": ok,
                "conversations_reused_incremental": reused,
                "conversations_errors": len(errs),
                "workspaces_discovered": len(workspaces),
                "assets_discovered": len(assets),
                "scheduled_tasks_active": len(tasks.get("active") or []),
                "scheduled_tasks_inactive": len(tasks.get("inactive") or []),
            },
            "errors": {"conversations": errs[:50]},
        }

        log_jsonl = output_dir / "capture_log.jsonl"
        with open(log_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")

        _write_last_capture_md(output_dir, log)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        return output_dir
    finally:
        await context.close()
