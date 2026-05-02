"""Orchestrator Gemini — pasta unica cumulativa per-account.

Layout:
    data/raw/Gemini/account-{N}/
        conversations/<uuid>.json
        discovery_ids.json
        capture_log.jsonl
        LAST_CAPTURE.md

Multi-conta: orchestrator cobre 1 conta por chamada (`account=1` ou `account=2`).
Sync orchestrador (`scripts/gemini-sync.py`) itera ambas.

Modo default: incremental (re-fetch so convs com created_at_secs != conhecido OR
arquivo nao existe).

Fail-fast: aborta se discovery cair >20% vs maior valor historico — protege
contra batchexecute flakey (rpcid hash mudando, response 400, etc).
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.gemini.auth import load_context
from src.extractors.gemini.api_client import GeminiAPIClient
from src.extractors.gemini.batchexecute import load_session
from src.extractors.gemini.discovery import discover, persist_discovery
from src.extractors.gemini.fetcher import fetch_conversations


BASE_DIR = Path("data/raw/Gemini")

# Aborta captura se discovery cair mais que isso vs maior valor historico.
DISCOVERY_DROP_ABORT_THRESHOLD = 0.20


def _account_dir(account: int) -> Path:
    return BASE_DIR / f"account-{account}"


def _get_max_known_discovery(account_dir: Path) -> int:
    """Maior conversations_discovered ja visto em qualquer capture_log da conta."""
    if not account_dir.exists():
        return 0
    max_count = 0
    for log_path in account_dir.rglob("capture_log.jsonl"):
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
    # Backward compat: capture_log.json (legacy snapshot)
    for log_path in account_dir.rglob("capture_log.json"):
        try:
            with open(log_path) as f:
                data = json.load(f)
            count = (data.get("totals") or {}).get("conversations_discovered", 0)
            if count > max_count:
                max_count = count
        except Exception:
            continue
    return max_count


def _existing_disc_map(account_dir: Path) -> dict[str, int]:
    """Le discovery_ids.json existente -> {uuid: created_at_secs}."""
    disc = account_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    try:
        data = json.loads(disc.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {c["uuid"]: c.get("created_at_secs", 0) or 0 for c in data if c.get("uuid")}


def _write_last_capture_md(output_dir: Path, log: dict) -> None:
    totals = log.get("totals", {})
    md = (
        "# Last capture\n\n"
        f"- **Quando:** {log.get('finished_at')}\n"
        f"- **Account:** {log.get('account')}\n"
        f"- **Modo:** {log.get('mode')}\n"
        f"- **Conversations:** {totals.get('conversations_discovered', 0)} discovered, "
        f"{totals.get('conversations_fetched', 0)} fetched, "
        f"{totals.get('conversations_reused_incremental', 0)} reused\n"
        f"- **Errors:** convs={totals.get('conversations_errors', 0)}\n\n"
        "Ver `capture_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_CAPTURE.md").write_text(md, encoding="utf-8")


async def run_export(
    account: int = 1,
    full: bool = False,
    smoke_limit: int | None = None,
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = _account_dir(account)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    # Modo incremental: estado anterior vem da propria pasta unica
    prev_map = {} if full else _existing_disc_map(output_dir)
    if prev_map and not full:
        print(f"Modo incremental: {len(prev_map)} convs no estado anterior")
    else:
        print("Modo full")

    context = await load_context(account=account, headless=True)
    try:
        session = await load_session(context)
        client = GeminiAPIClient(context, session)

        convs = await discover(client, output_dir)

        # Fail-fast: queda drastica vs baseline historico. Persistencia da
        # discovery acontece SO depois do clear — escrever antes corrompe
        # baseline incremental se abortar.
        baseline = _get_max_known_discovery(output_dir)
        curr = len(convs)
        if baseline > 0:
            drop = (baseline - curr) / baseline
            if drop > DISCOVERY_DROP_ABORT_THRESHOLD:
                raise RuntimeError(
                    f"Discovery suspeita: {curr} convs vs {baseline} no historico "
                    f"(queda {drop:.0%}, limite {DISCOVERY_DROP_ABORT_THRESHOLD:.0%}). "
                    f"Provavel rpcid MaZiqc/hNvQHb hash mudou — checar com probe."
                )
            print(f"Discovery OK: {curr} convs (baseline historico: {baseline})")

        persist_discovery(convs, output_dir)

        today = started_at.strftime("%Y-%m-%d")
        conv_dir = output_dir / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)

        # Cutoff: re-fetcha so convs com created_at_secs novo OR arquivo nao existe.
        # Nota: Gemini nao expoe updated_at (apenas created_at_secs). Mensagem
        # nova numa conv existente NAO bumpa created_at — pra forcar refetch
        # nesses casos use --full.
        to_fetch: list[str] = []
        reused = 0
        for c in convs:
            uid = c["uuid"]
            curr_secs = c.get("created_at_secs") or 0
            prev_secs = prev_map.get(uid, 0)
            existing = conv_dir / f"{uid}.json"
            if uid in prev_map and prev_secs == curr_secs and existing.exists():
                # Atualiza _last_seen_in_server in-place sem refetch
                try:
                    obj = json.loads(existing.read_text(encoding="utf-8"))
                    obj["_last_seen_in_server"] = today
                    existing.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                    reused += 1
                    continue
                except Exception:
                    pass
            to_fetch.append(uid)

        if smoke_limit is not None:
            to_fetch = to_fetch[:smoke_limit]
            print(f"SMOKE: limitado a {smoke_limit} convs")

        print(f"Fetching {len(to_fetch)} convs ({reused} reusadas)")
        # skip_existing=False porque o filtro de cima ja decidiu quem refetchar.
        # Sem isso, full mode ainda pula bodies locais e nao captura mudancas.
        ok, skipped, errs = await fetch_conversations(
            client, to_fetch, output_dir, concurrency=2, skip_existing=False,
        )

        # Tag _last_seen_in_server nos arquivos recem-fetched
        for uid in to_fetch:
            f = conv_dir / f"{uid}.json"
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
            "account": account,
            "mode": "full" if full else "incremental",
            "smoke_limit": smoke_limit,
            "totals": {
                "conversations_discovered": len(convs),
                "conversations_fetched": ok,
                "conversations_reused_incremental": reused,
                "conversations_errors": len(errs),
            },
            "errors": {"conversations": errs[:50]},
        }

        # Append em capture_log.jsonl
        log_jsonl = output_dir / "capture_log.jsonl"
        with open(log_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")

        # Snapshot human-readable
        _write_last_capture_md(output_dir, log)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        return output_dir
    finally:
        await context.close()
