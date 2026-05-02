"""Orchestrator Qwen: pasta unica cumulativa em data/raw/Qwen/.

Padrao alinhado com ChatGPT, Claude.ai e Perplexity (sem timestamp, sem
subpastas datadas). Conversations + projects + assets cumulativos no mesmo
path.

Modo default: incremental — re-fetcha so chats com updated_at > o que ja
temos em disco. Chats inalterados ficam intocados.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.qwen.auth import load_context
from src.extractors.qwen.api_client import QwenAPIClient
from src.extractors.qwen.discovery import discover, persist_discovery
from src.extractors.qwen.fetcher import fetch_conversations


BASE_DIR = Path("data/raw/Qwen")

logger = logging.getLogger(__name__)


# Aborta captura se discovery cair mais que isso vs maior valor historico.
DISCOVERY_DROP_ABORT_THRESHOLD = 0.20


def _get_max_known_discovery(raw_root: Path) -> int:
    """Maior chats_discovered ja visto em qualquer capture_log."""
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
    # Backward compat: capture_log.json antigo (formato snapshot)
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


def _existing_disc_map(raw_dir: Path) -> dict[str, int]:
    """Le discovery_ids.json existente -> {id: updated_at}.

    Pasta unica cumulativa: a propria pasta serve de baseline incremental.
    """
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    try:
        data = json.loads(disc.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {c["id"]: c.get("updated_at", 0) or 0 for c in data if c.get("id")}


def _write_last_capture_md(output_dir: Path, log: dict) -> None:
    """LAST_CAPTURE.md — snapshot human-readable, sobrescreve a cada run."""
    totals = log.get("totals", {})
    md = (
        "# Last capture\n\n"
        f"- **Quando:** {log.get('finished_at')}\n"
        f"- **Modo:** {log.get('mode')}\n"
        f"- **Conversations:** {totals.get('conversations_discovered', 0)} discovered, "
        f"{totals.get('conversations_fetched', 0)} fetched, "
        f"{totals.get('conversations_reused_incremental', 0)} reused\n"
        f"- **Projects:** {totals.get('projects_discovered', 0)}\n"
        f"- **Errors:** convs={totals.get('conversations_errors', 0)}\n\n"
        "Ver `capture_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_CAPTURE.md").write_text(md, encoding="utf-8")


async def run_export(
    full: bool = False,
    smoke_limit: int | None = None,
    account: str = "default",
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = BASE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    # Modo incremental: estado anterior vem da propria pasta unica
    prev_map = {} if full else _existing_disc_map(output_dir)
    if prev_map and not full:
        print(f"Modo incremental: {len(prev_map)} chats no estado anterior")
    else:
        print("Modo full")

    context = await load_context(account=account, headless=True)
    try:
        page = await context.new_page()
        client = QwenAPIClient(context, page)
        await client.warmup()

        chats, projects_disc = await discover(client, output_dir)

        # Fail-fast: queda drastica. Persistencia da discovery acontece SO depois
        # do clear — escrever antes corrompe baseline incremental se abortar.
        baseline = _get_max_known_discovery(output_dir)
        curr = len(chats)
        if baseline > 0:
            drop = (baseline - curr) / baseline
            if drop > DISCOVERY_DROP_ABORT_THRESHOLD:
                raise RuntimeError(
                    f"Discovery suspeita: {curr} chats vs {baseline} no historico "
                    f"(queda {drop:.0%}, limite {DISCOVERY_DROP_ABORT_THRESHOLD:.0%}). "
                    f"Tente novamente."
                )
            print(f"Discovery OK: {curr} chats (baseline historico: {baseline})")

        persist_discovery(chats, projects_disc, output_dir)

        today = started_at.strftime("%Y-%m-%d")
        conv_dir = output_dir / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)

        # Cutoff: re-fetcha so chats com updated_at novo (ou se file local nao existe)
        to_fetch: list[str] = []
        reused = 0
        for c in chats:
            cid = c["id"]
            curr_upd = c.get("updated_at") or 0
            prev_upd = prev_map.get(cid, 0)
            existing = conv_dir / f"{cid}.json"
            if cid in prev_map and prev_upd == curr_upd and existing.exists():
                # Atualiza _last_seen_in_server in-place sem refetch
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
        # skip_existing=False porque ja decidimos quais fetchar
        ok, skipped, errs = await fetch_conversations(
            client, to_fetch, output_dir, skip_existing=False
        )

        # Tag _last_seen_in_server nos arquivos recem-fetched
        for cid in to_fetch:
            f = conv_dir / f"{cid}.json"
            if f.exists():
                try:
                    obj = json.loads(f.read_text(encoding="utf-8"))
                    obj["_last_seen_in_server"] = today
                    f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass

        # Projects ja foram listados+persistidos no persist_discovery acima
        projects = projects_disc

        # Build log
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
                "projects_discovered": len(projects) if projects else 0,
            },
            "errors": {"conversations": errs[:50]},
        }

        # Append em capture_log.jsonl
        log_jsonl = output_dir / "capture_log.jsonl"
        with open(log_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")

        # LAST_CAPTURE.md
        _write_last_capture_md(output_dir, log)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        return output_dir
    finally:
        await context.close()
