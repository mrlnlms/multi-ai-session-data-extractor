"""Orchestrator Kimi: pasta unica cumulativa em data/raw/Kimi/.

Padrao alinhado com Qwen/DeepSeek/Grok. Conversations + skills + assets
cumulativos no mesmo path. Modo default: incremental — re-fetcha so
chats com updateTime > o que ja temos em disco.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.kimi.auth import load_context
from src.extractors.kimi.api_client import KimiAPIClient
from src.extractors.kimi.discovery import discover, persist_discovery
from src.extractors.kimi.fetcher import fetch_conversations
from src.extractors.kimi.refetch_known import refetch_known_kimi


BASE_DIR = Path("data/raw/Kimi")

logger = logging.getLogger(__name__)


# Quando discovery cai mais que isso vs maior valor historico, o orchestrator
# nao confia no listing e cai pra refetch_known via fetch_full_chat por ID
# (caminho que nao depende de discovery — pega pelos IDs ja salvos no raw
# cumulativo). Threshold mantido pra evitar falso-fallback (oscilacoes pequenas
# sao normais).
DISCOVERY_DROP_FALLBACK_THRESHOLD = 0.20
# Alias retro-compat (codigo/testes antigos referenciam pelo nome velho)
DISCOVERY_DROP_ABORT_THRESHOLD = DISCOVERY_DROP_FALLBACK_THRESHOLD


def _get_max_known_discovery(raw_root: Path) -> int:
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
    """Le discovery_ids.json existente -> {id: updateTime}."""
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    try:
        data = json.loads(disc.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {c["id"]: c.get("updateTime") or "" for c in data if c.get("id")}


def _write_last_capture_md(output_dir: Path, log: dict) -> None:
    totals = log.get("totals", {})
    md = (
        "# Last capture\n\n"
        f"- **Quando:** {log.get('finished_at')}\n"
        f"- **Modo:** {log.get('mode')}\n"
        f"- **Conversations:** {totals.get('conversations_discovered', 0)} discovered, "
        f"{totals.get('conversations_fetched', 0)} fetched, "
        f"{totals.get('conversations_reused_incremental', 0)} reused\n"
        f"- **Skills:** {totals.get('skills_official', 0)} oficiais, "
        f"{totals.get('skills_installed', 0)} instaladas\n"
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
        print(f"Modo incremental: {len(prev_map)} chats no estado anterior")
    else:
        print("Modo full")

    context = await load_context(account=account, headless=headless)
    try:
        page = await context.new_page()
        client = KimiAPIClient(context, page)
        await client.warmup()

        chats, skills_official, skills_installed = await discover(client)

        # Discovery parcial vira fallback automatico pra refetch_known.
        # ListChats as vezes retorna paginacao incompleta — em vez de confiar
        # nesse listing reduzido (e marcar centenas como deletadas), cai pra
        # refetch_known via fetch_full_chat por ID usando os arquivos ja
        # salvos no raw cumulativo.
        # Persistencia da discovery acontece SO depois do clear/fallback —
        # escrever antes corrompe baseline incremental no proximo run.
        baseline = _get_max_known_discovery(output_dir)
        curr = len(chats)
        if baseline > 0:
            drop = (baseline - curr) / baseline
            if drop > DISCOVERY_DROP_FALLBACK_THRESHOLD:
                logger.warning(
                    f"Discovery parcial: {curr} chats vs {baseline} no historico "
                    f"(queda {drop:.0%}). Caindo pra refetch_known via fetch_full_chat."
                )
                stats = await refetch_known_kimi(client, output_dir)
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
                        "skills_official": len(skills_official),
                        "skills_installed": len(skills_installed),
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
            print(f"Discovery OK: {curr} chats (baseline historico: {baseline})")

        persist_discovery(chats, skills_official, skills_installed, output_dir)

        today = started_at.strftime("%Y-%m-%d")
        conv_dir = output_dir / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)

        to_fetch: list[str] = []
        reused = 0
        for c in chats:
            cid = c.get("id")
            if not cid:
                continue
            curr_upd = c.get("updateTime") or ""
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
            print(f"SMOKE: limitado a {smoke_limit} chats")

        print(f"Fetching {len(to_fetch)} chats ({reused} reusados)")
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
                "conversations_discovered": len(chats),
                "conversations_fetched": ok,
                "conversations_reused_incremental": reused,
                "conversations_errors": len(errs),
                "skills_official": len(skills_official),
                "skills_installed": len(skills_installed),
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
