"""Orchestrator Claude.ai: pasta unica cumulativa em data/raw/Claude.ai/.

Padrao alinhado com ChatGPT e Perplexity (sem timestamp, sem subpastas datadas).
Conversations + projects + assets metadata todos cumulativos no mesmo path.

Captura headless OK (sem desafio Cloudflare em runtime, so login eh headed).

Modo default: incremental — re-fetcha so convs com updated_at > o que ja temos
em disco. Convs inalteradas ficam intocadas.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.platforms.claude_ai.extractor.auth import load_context
from src.platforms.claude_ai.extractor.api_client import ClaudeAPIClient
from src.platforms.claude_ai.extractor.account_memory import capture_account_memory
from src.platforms.claude_ai.extractor.discovery import discover, persist_discovery
from src.platforms.claude_ai.extractor.fetcher import fetch_conversations, fetch_projects
from src.platforms.claude_ai.extractor.refetch_known import refetch_known_claude_ai
from src.accounts import account_data_dir


BASE_DIR = Path("data/raw/Claude.ai")

logger = logging.getLogger(__name__)


# Quando discovery cai mais que isso vs maior valor historico, o orchestrator
# nao confia no listing e cai pra refetch_known via client.fetch_conversation
# (caminho que nao depende de discovery — pega pelos IDs ja salvos no raw
# cumulativo). Threshold mantido pra evitar falso-fallback (oscilacoes pequenas
# sao normais).
DISCOVERY_DROP_FALLBACK_THRESHOLD = 0.20
# Alias retro-compat (codigo/testes antigos referenciam pelo nome velho)
DISCOVERY_DROP_ABORT_THRESHOLD = DISCOVERY_DROP_FALLBACK_THRESHOLD


def _get_max_known_discovery(raw_root: Path) -> int:
    """Maior discovery.total ja visto em qualquer capture_log.

    Recursivo de proposito — pega capture_logs em subpastas (ex: _backup-*),
    pra que mover raws antigos pra subpasta nao reseta a baseline.
    """
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


def _existing_disc_map(raw_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Le discovery_ids.json existente -> ({conv_uuid: updated_at}, {proj_uuid: updated_at}).

    Pasta unica cumulativa: a propria pasta serve de baseline incremental.
    """
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}, {}
    try:
        data = json.loads(disc.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    convs = {c["uuid"]: c.get("updated_at", "") or "" for c in data.get("conversations", []) if c.get("uuid")}
    projs = {p["uuid"]: p.get("updated_at", "") or "" for p in data.get("projects", []) if p.get("uuid")}
    return convs, projs


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
        f"- **Projects:** {totals.get('projects_discovered', 0)} discovered, "
        f"{totals.get('projects_fetched', 0)} fetched, "
        f"{totals.get('projects_skipped_existing', 0)} skipped\n"
        f"- **Errors:** convs={totals.get('conversations_errors', 0)}, "
        f"projects={totals.get('projects_errors', 0)}\n"
        f"- **Memory:** {log.get('memory_capture', {}).get('status', 'not_attempted')} "
        f"({log.get('memory_capture', {}).get('topics', 0)} topics)\n\n"
        "Ver `capture_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_CAPTURE.md").write_text(md, encoding="utf-8")


async def _capture_memory_safe(client: ClaudeAPIClient, output_dir: Path) -> dict:
    """Keep conversation capture independent, but record memory coverage durably."""
    try:
        result = await capture_account_memory(client, output_dir)
        status = "complete" if result["complete"] else "incomplete"
        summary = {"status": status, "topics": result["topics"],
                   "failed_reads": result["failed_reads"],
                   "settings_error": result["settings_error"]}
        print(f"Memory: {summary['topics']} topics; status={status}")
        return summary
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning("Claude memory capture failed (%s)", error_type)
        return {"status": "error", "topics": 0, "failed_reads": 0,
                "error_type": error_type}


async def run_export(
    profile_name: str = "default",
    full: bool = False,
    smoke_limit: int | None = None,
    headless: bool = True,
    output_dir: Path | None = None,
) -> Path:
    """Roda o pipeline completo: discovery + fetch convs + fetch projects.

    Args:
        profile_name: profile Playwright (default='default')
        full: se True, re-fetch tudo (ignora cutoff incremental)
        smoke_limit: se setado, so fetcha N convs (smoke test)
        headless: True por default (Claude.ai aceita headless em runtime)

    Returns:
        Path do diretorio raw da conta.
    """
    started_at = datetime.now(timezone.utc)
    output_dir = output_dir or account_data_dir(BASE_DIR, profile_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    # Modo incremental: estado anterior vem da propria pasta unica
    prev_convs, prev_projs = ({}, {}) if full else _existing_disc_map(output_dir)
    if (prev_convs or prev_projs) and not full:
        print(
            f"Modo incremental: {len(prev_convs)} convs + {len(prev_projs)} projects "
            f"no estado anterior"
        )
    else:
        print("Modo full (sem cutoff incremental)")

    context, org_id = await load_context(profile_name=profile_name, headless=headless)
    client = ClaudeAPIClient(context, org_id)

    try:
        # Discovery
        disc = await discover(client, output_dir)

        # Discovery parcial vira fallback automatico pra refetch_known.
        # Em vez de confiar num listing reduzido (e marcar centenas como deletadas),
        # cai pra refetch_known via client.fetch_conversation usando os IDs ja
        # salvos no raw cumulativo. Persistencia da discovery NAO acontece nesse
        # caminho — escrever um listing parcial corrompe baseline incremental.
        baseline = _get_max_known_discovery(output_dir)
        curr = len(disc["conversations"])
        if baseline > 0:
            drop = (baseline - curr) / baseline
            if drop > DISCOVERY_DROP_FALLBACK_THRESHOLD:
                logger.warning(
                    f"Discovery parcial: {curr} convs vs {baseline} no historico "
                    f"(queda {drop:.0%}). Caindo pra refetch_known via "
                    f"client.fetch_conversation."
                )
                stats = await refetch_known_claude_ai(client, output_dir)

                # Memory is independent of conversation discovery.
                memory_capture = await _capture_memory_safe(client, output_dir)

                finished_at = datetime.now(timezone.utc)
                log = {
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "org_id": org_id,
                    "mode": "refetch_known_fallback",
                    "smoke_limit": smoke_limit,
                    "headless": headless,
                    "memory_capture": memory_capture,
                    "totals": {
                        "conversations_discovered": stats["total"],
                        "conversations_fetched": stats["updated"],
                        "conversations_skipped_existing": 0,
                        "conversations_reused_incremental": 0,
                        "conversations_errors": stats["errors"],
                        "projects_discovered": 0,
                        "projects_fetched": 0,
                        "projects_skipped_existing": 0,
                        "projects_reused_incremental": 0,
                        "projects_errors": 0,
                    },
                    "errors": {"conversations": [], "projects": []},
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

        persist_discovery(disc, output_dir)

        today = started_at.strftime("%Y-%m-%d")

        # Cutoff incremental conversations: re-fetcha so updated_at > o que temos
        # E re-fetcha tambem se o file local nao existe (recovery de capture incompleta)
        conv_dir = output_dir / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)
        convs_to_fetch: list[str] = []
        reused = 0
        for c in disc["conversations"]:
            uid = c["uuid"]
            curr_ut = c.get("updated_at", "") or ""
            prev_ut = prev_convs.get(uid, "")
            existing = conv_dir / f"{uid}.json"
            if uid in prev_convs and prev_ut == curr_ut and existing.exists():
                # Atualiza _last_seen_in_server in-place sem re-fetchar
                try:
                    obj = json.loads(existing.read_text(encoding="utf-8"))
                    obj["_last_seen_in_server"] = today
                    existing.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                    reused += 1
                    continue
                except Exception:
                    pass  # corromp — re-fetcha
            convs_to_fetch.append(uid)

        if smoke_limit is not None:
            convs_to_fetch = convs_to_fetch[:smoke_limit]
            print(f"SMOKE MODE: limitado a {smoke_limit} convs")

        print(f"Fetching {len(convs_to_fetch)} convs ({reused} reusadas)")
        # skip_existing=False porque ja decidimos quais fetchar acima
        conv_ok, conv_skip, conv_errs = await fetch_conversations(
            client, convs_to_fetch, output_dir, concurrency=3, skip_existing=False
        )

        # Tag _last_seen_in_server nos arquivos recem-fetched
        for uid in convs_to_fetch:
            f = conv_dir / f"{uid}.json"
            if f.exists():
                try:
                    obj = json.loads(f.read_text(encoding="utf-8"))
                    obj["_last_seen_in_server"] = today
                    f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass

        # Projects: cutoff por updated_at tambem, mas projects sao baratos — re-fetcha sempre se mudou
        proj_dir = output_dir / "projects"
        proj_dir.mkdir(parents=True, exist_ok=True)
        projs_to_fetch: list[str] = []
        proj_reused = 0
        for p in disc["projects"]:
            uid = p["uuid"]
            curr_ut = p.get("updated_at", "") or ""
            prev_ut = prev_projs.get(uid, "")
            existing = proj_dir / f"{uid}.json"
            if uid in prev_projs and prev_ut == curr_ut and existing.exists():
                proj_reused += 1
                continue
            projs_to_fetch.append(uid)

        if smoke_limit is not None:
            projs_to_fetch = projs_to_fetch[:5]

        print(f"Fetching {len(projs_to_fetch)} projects ({proj_reused} reusados)")
        proj_ok, proj_skip, proj_errs = await fetch_projects(
            client, projs_to_fetch, output_dir, concurrency=3, skip_existing=False
        )

        # Native account and project memories, independent of conversations.
        memory_capture = await _capture_memory_safe(client, output_dir)

        # Build log
        log = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "org_id": org_id,
            "mode": "full" if full else "incremental",
            "smoke_limit": smoke_limit,
            "headless": headless,
            "memory_capture": memory_capture,
            "totals": {
                "conversations_discovered": len(disc["conversations"]),
                "conversations_fetched": conv_ok,
                "conversations_skipped_existing": conv_skip,
                "conversations_reused_incremental": reused,
                "conversations_errors": len(conv_errs),
                "projects_discovered": len(disc["projects"]),
                "projects_fetched": proj_ok,
                "projects_skipped_existing": proj_skip,
                "projects_reused_incremental": proj_reused,
                "projects_errors": len(proj_errs),
            },
            "errors": {
                "conversations": conv_errs[:50],
                "projects": proj_errs[:50],
            },
        }

        # Append em capture_log.jsonl (historico cumulativo)
        log_jsonl = output_dir / "capture_log.jsonl"
        with open(log_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")

        # LAST_CAPTURE.md (snapshot)
        _write_last_capture_md(output_dir, log)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        print("Proximo passo: PYTHONPATH=. .venv/bin/python -m src.platforms.claude_ai.commands.download_assets")
        return output_dir
    finally:
        await context.close()
