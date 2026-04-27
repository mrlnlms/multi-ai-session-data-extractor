"""Orchestrator: amarra auth + discovery + fetcher + capture_log.

Separa asset download: fica pro claude-download-assets.py (padrao ChatGPT).

Modo default: incremental, detecta raw anterior em data/raw/Claude Data <YYYY-MM-DD-...>/
e pula convs que nao mudaram (updated_at igual).
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.claude_ai.auth import load_context
from src.extractors.claude_ai.api_client import ClaudeAPIClient
from src.extractors.claude_ai.discovery import discover
from src.extractors.claude_ai.fetcher import fetch_conversations, fetch_projects


RAW_BASE = Path("data/raw")


def _make_output_dir() -> Path:
    """data/raw/Claude Data <YYYY-MM-DDTHH-MM>/"""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
    return RAW_BASE / f"Claude Data {ts}"


def _find_previous_raw(exclude: Path | None = None) -> Path | None:
    """Acha o raw anterior mais recente pra cutoff incremental.

    Olha tudo que bate 'Claude Data *' em data/raw/. Opcionalmente exclui um
    path (usado pra nao self-match quando o output dir acabou de ser criado).
    """
    if not RAW_BASE.exists():
        return None
    candidates = [
        p for p in RAW_BASE.iterdir()
        if p.is_dir() and p.name.startswith("Claude Data ")
        and (exclude is None or p.resolve() != exclude.resolve())
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _updated_at_map(raw_dir: Path) -> dict[str, str]:
    """Le discovery_ids.json do raw anterior pra cutoff."""
    disc = raw_dir / "discovery_ids.json"
    if not disc.exists():
        return {}
    with open(disc, encoding="utf-8") as f:
        data = json.load(f)
    return {c["uuid"]: c.get("updated_at", "") for c in data.get("conversations", [])}


async def run_export(
    profile_name: str = "default",
    full: bool = False,
    smoke_limit: int | None = None,
) -> Path:
    """Roda o pipeline completo: discovery + fetch convs + fetch projects.

    Args:
        profile_name: profile Playwright (default='default')
        full: se True, re-fetch tudo (ignora cutoff incremental)
        smoke_limit: se setado, so fetcha N convs (pra smoke test)

    Returns:
        Path do diretorio raw criado.
    """
    started_at = datetime.now(timezone.utc)
    output_dir = _make_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raw output: {output_dir}")

    # Determina cutoff incremental (exclui o output_dir recem-criado pra nao self-match)
    prev_raw = None if full else _find_previous_raw(exclude=output_dir)
    prev_updated = _updated_at_map(prev_raw) if prev_raw else {}
    if prev_raw:
        print(f"Modo incremental: cutoff vs {prev_raw.name} ({len(prev_updated)} convs conhecidas)")
    else:
        print("Modo full (sem cutoff incremental)")

    # Auth + client
    context, org_id = await load_context(profile_name=profile_name, headless=True)
    client = ClaudeAPIClient(context, org_id)

    try:
        # Discovery
        disc = await discover(client, output_dir)

        # Cutoff: filtra convs que ja temos com mesmo updated_at
        convs_to_fetch = []
        reused = 0
        for c in disc["conversations"]:
            uid = c["uuid"]
            if uid in prev_updated and prev_updated[uid] == c.get("updated_at"):
                # Copia o arquivo antigo direto (preserva)
                old = prev_raw / "conversations" / f"{uid}.json"
                new = output_dir / "conversations" / f"{uid}.json"
                new.parent.mkdir(parents=True, exist_ok=True)
                if old.exists():
                    new.write_bytes(old.read_bytes())
                    reused += 1
                    continue
            convs_to_fetch.append(uid)

        if smoke_limit is not None:
            convs_to_fetch = convs_to_fetch[:smoke_limit]
            print(f"SMOKE MODE: limitado a {smoke_limit} convs")

        print(f"Fetching {len(convs_to_fetch)} convs ({reused} reusadas do incremental)")
        conv_ok, conv_skip, conv_errs = await fetch_conversations(
            client, convs_to_fetch, output_dir, concurrency=3
        )

        # Projects: sempre todos (nao daotimo incremental — e rapido)
        project_uuids = [p["uuid"] for p in disc["projects"]]
        if smoke_limit is not None:
            project_uuids = project_uuids[:5]
        print(f"Fetching {len(project_uuids)} projects")
        proj_ok, proj_skip, proj_errs = await fetch_projects(
            client, project_uuids, output_dir, concurrency=3
        )

        # capture log
        log = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "org_id": org_id,
            "mode": "full" if full else "incremental",
            "smoke_limit": smoke_limit,
            "previous_raw": str(prev_raw.name) if prev_raw else None,
            "totals": {
                "conversations_discovered": len(disc["conversations"]),
                "conversations_fetched": conv_ok,
                "conversations_skipped_existing": conv_skip,
                "conversations_reused_incremental": reused,
                "conversations_errors": len(conv_errs),
                "projects_discovered": len(disc["projects"]),
                "projects_fetched": proj_ok,
                "projects_skipped_existing": proj_skip,
                "projects_errors": len(proj_errs),
            },
            "errors": {
                "conversations": conv_errs[:50],
                "projects": proj_errs[:50],
            },
        }
        with open(output_dir / "capture_log.json", "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

        print()
        print("=== SUMMARY ===")
        print(json.dumps(log["totals"], indent=2))
        print(f"\nRaw em: {output_dir}")
        print("Proximo passo: python scripts/claude-download-assets.py")
        return output_dir
    finally:
        await context.close()
