"""Orchestrator Perplexity: pasta unica cumulativa em data/raw/Perplexity/.

Padrao alinhado com ChatGPT (sem timestamp, sem subpastas datadas).
Threads, spaces, pages, assets metadata + binarios todos cumulativos.

Default headless=False pra passar Cloudflare challenge.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.perplexity.auth import load_context
from src.extractors.perplexity.api_client import PerplexityAPIClient
from src.extractors.perplexity.discovery import discover, persist_discovery
from src.extractors.perplexity.fetcher import fetch_threads
from src.extractors.perplexity.spaces import discover_spaces, fetch_spaces
from src.extractors.perplexity.artifact_downloader import download_artifacts
from src.extractors.perplexity.asset_downloader import download_assets as download_thread_attachments


BASE_DIR = Path("data/raw/Perplexity")

# Aborta captura se discovery cair mais que isso vs maior valor historico.
DISCOVERY_DROP_ABORT_THRESHOLD = 0.20


def _get_max_known_discovery(raw_root: Path) -> int:
    """Maior threads_discovered ja visto em qualquer capture_log."""
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
                    count = (data.get("totals") or {}).get("threads_discovered", 0)
                    if count > max_count:
                        max_count = count
        except Exception:
            continue
    return max_count


def _tag_map(raw_dir: Path) -> dict[str, str]:
    """Le discovery_ids.json existente -> {uuid: last_query_datetime}."""
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    with open(disc, encoding="utf-8") as f:
        data = json.load(f)
    return {t["uuid"]: t.get("last_query_datetime", "") or "" for t in data}


def _write_last_capture_md(output_dir: Path, log: dict) -> None:
    """Regenera LAST_CAPTURE.md com snapshot da run."""
    totals = log.get("totals", {})
    md = (
        "# Last capture\n\n"
        f"- **Quando:** {log.get('finished_at')}\n"
        f"- **Modo:** {log.get('mode')}\n"
        f"- **Threads:** {totals.get('threads_discovered', 0)} discovered, "
        f"{totals.get('threads_fetched', 0)} fetched, "
        f"{totals.get('threads_reused_incremental', 0)} reused\n"
        f"- **Spaces:** {totals.get('spaces_discovered', 0)} ({totals.get('spaces_pinned', 0)} pinados)\n"
        f"- **Assets (artifacts):** {totals.get('assets_total', 0)} metadata, "
        f"{totals.get('assets_downloaded', 0) + totals.get('assets_download_skipped', 0)} binarios em disco\n"
        f"- **Thread attachments:** {totals.get('thread_attachments_downloaded', 0)} dl, "
        f"{totals.get('thread_attachments_errors', 0)} irrecuperaveis (S3 cleanup upstream)\n"
        f"- **Errors:** threads={totals.get('threads_errors', 0)}, spaces={totals.get('spaces_errors', 0)}\n\n"
        "Ver `capture_log.jsonl` pro historico completo.\n"
    )
    (output_dir / "LAST_CAPTURE.md").write_text(md, encoding="utf-8")


async def run_export(
    full: bool = False,
    smoke_limit: int | None = None,
    account: str = "default",
    headless: bool = False,
) -> Path:
    started_at = datetime.now(timezone.utc)
    output_dir = BASE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    # Modo incremental: tag_map vem da propria pasta unica (estado atual)
    prev_map = {} if full else _tag_map(output_dir)
    if prev_map and not full:
        print(f"Modo incremental: {len(prev_map)} threads no estado anterior")
    else:
        print("Modo full")

    context = await load_context(account=account, headless=headless)
    try:
        page = await context.new_page()
        client = PerplexityAPIClient(context, page)
        await client.warmup()

        # User metadata (info, settings, ai_profile) — preservation completa
        print("Capturando user metadata...")
        user_dir = output_dir / "user"
        user_dir.mkdir(parents=True, exist_ok=True)
        try:
            (user_dir / "info.json").write_text(
                json.dumps(await client.get_user_info(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (user_dir / "settings.json").write_text(
                json.dumps(await client.get_user_settings(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (user_dir / "ai_profile.json").write_text(
                json.dumps(await client.get_user_ai_profile(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (user_dir / "skills.json").write_text(
                json.dumps(await client.list_user_skills(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"  warn user metadata: {str(e)[:100]}")

        threads = await discover(client, output_dir)

        # Fail-fast: queda drastica vs baseline historico. Persistencia da
        # discovery acontece SO depois do clear — escrever antes corrompe
        # baseline incremental se abortar (mesmo bug 2 corrigido em qwen/
        # deepseek/gemini/claude_ai).
        baseline = _get_max_known_discovery(output_dir)
        curr = len(threads)
        if baseline > 0:
            drop = (baseline - curr) / baseline
            if drop > DISCOVERY_DROP_ABORT_THRESHOLD:
                raise RuntimeError(
                    f"Discovery suspeita: {curr} threads vs {baseline} no historico "
                    f"(queda {drop:.0%}, limite {DISCOVERY_DROP_ABORT_THRESHOLD:.0%}). "
                    f"Possivel Cloudflare challenge / sessao expirada / endpoint flakey. "
                    f"Tente novamente."
                )
            print(f"Discovery OK: {curr} threads (baseline historico: {baseline})")

        persist_discovery(threads, output_dir)

        # Plano incremental: thread JA existe no disco com mesmo last_query_datetime?
        # Mantem (skip fetch). Mudou ou nova → fetch.
        to_fetch = []
        reused = 0
        for t in threads:
            uid = t.get("uuid")
            if not uid:
                continue
            tag = t.get("last_query_datetime", "") or ""
            existing = output_dir / "threads" / f"{uid}.json"
            if uid in prev_map and prev_map[uid] == tag and existing.exists():
                reused += 1
                continue
            to_fetch.append(uid)

        if smoke_limit is not None:
            to_fetch = to_fetch[:smoke_limit]
            print(f"SMOKE: limitado a {smoke_limit} threads")

        print(f"Fetching {len(to_fetch)} threads ({reused} reusadas)")
        ok, skipped, errs = await fetch_threads(client, to_fetch, output_dir)

        # Spaces (collections) + pages
        collections = await discover_spaces(client, output_dir)
        spaces_pinned_count = sum(1 for c in collections if c.get("uuid") and (output_dir / "spaces" / "_pinned_raw.json").exists())
        # pinned count real vai do _pinned_raw.json
        try:
            pinned_data = json.loads((output_dir / "spaces" / "_pinned_raw.json").read_text(encoding="utf-8"))
            spaces_pinned_count = len(pinned_data) if isinstance(pinned_data, list) else 0
        except Exception:
            spaces_pinned_count = 0
        spaces_ok, _, spaces_errs = await fetch_spaces(client, collections, output_dir, page=page)

        # Assets (artifacts)
        print("Capturando assets (artifacts)...")
        assets_all = await client.list_user_assets()
        assets_pinned = await client.list_user_pinned_assets()
        pinned_ids = {a.get("uuid") or a.get("id") for a in assets_pinned}
        assets_dir = output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        with open(assets_dir / "_index.json", "w", encoding="utf-8") as f:
            json.dump(
                [{**a, "is_pinned": (a.get("uuid") or a.get("id")) in pinned_ids} for a in assets_all],
                f, ensure_ascii=False, indent=2,
            )
        with open(assets_dir / "_pinned_raw.json", "w", encoding="utf-8") as f:
            json.dump(assets_pinned, f, ensure_ascii=False, indent=2)
        print(f"  {len(assets_all)} assets ({len(assets_pinned)} pinados)")

        # Download binarios artifacts
        if assets_all:
            print("Baixando binarios dos artifacts...")
            dl_stats = await download_artifacts(context, assets_all, output_dir)
            print(f"  downloaded={dl_stats['downloaded']} skipped_existing={dl_stats['skipped_existing']} failed={dl_stats['failed']}")
        else:
            dl_stats = {"downloaded": 0, "skipped_existing": 0, "failed": 0, "total": 0}

        # Thread attachments
        print("Baixando thread attachments + featured images...")
        try:
            att_stats = await download_thread_attachments(context, output_dir)
            print(f"  downloaded={att_stats['downloaded']} skipped={att_stats['skipped']} errors={len(att_stats['errors'])}")
        except Exception as e:
            print(f"  ERRO: {str(e)[:200]}")
            att_stats = {"downloaded": 0, "skipped": 0, "errors": [(None, str(e))]}

        log = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "full" if full else "incremental",
            "smoke_limit": smoke_limit,
            "headless": headless,
            "totals": {
                "threads_discovered": len(threads),
                "threads_fetched": ok,
                "threads_reused_incremental": reused,
                "threads_errors": len(errs),
                "spaces_discovered": len(collections),
                "spaces_pinned": spaces_pinned_count,
                "spaces_fetched": spaces_ok,
                "spaces_errors": len(spaces_errs),
                "assets_total": len(assets_all),
                "assets_pinned": len(assets_pinned),
                "assets_downloaded": dl_stats["downloaded"],
                "assets_download_skipped": dl_stats["skipped_existing"],
                "assets_download_failed": dl_stats["failed"],
                "thread_attachments_downloaded": att_stats.get("downloaded", 0),
                "thread_attachments_skipped": att_stats.get("skipped", 0),
                "thread_attachments_errors": len(att_stats.get("errors", [])),
            },
            "errors": {"threads": errs[:50], "spaces": spaces_errs[:20]},
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
        return output_dir
    finally:
        await context.close()
