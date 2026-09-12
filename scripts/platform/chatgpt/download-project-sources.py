"""Baixa knowledge files (sources) de todos os projects ChatGPT.

Uso: python scripts/chatgpt-download-project-sources.py [raw_dir]
Se nao passar raw_dir, usa o mais recente em data/raw/ChatGPT Data*/.

Descoberto empiricamente em 24/abr/2026 — endpoint
  GET /backend-api/files/download/{file_id}?gizmo_id={project_id}
libera download de knowledge files (sem gizmo_id da permission_error).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from src.extractors.chatgpt.api_client import ChatGPTAPIClient
from src.extractors.chatgpt.project_sources import download_project_sources


def _find_latest_raw() -> Path | None:
    base = Path("data/raw")
    candidates = sorted(
        [p for p in base.iterdir() if p.is_dir() and p.name.startswith("ChatGPT Data")],
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _collect_project_ids_from_raw(raw_dir: Path) -> list[str]:
    """Extrai project_ids unicos de chatgpt_raw.json."""
    rf = raw_dir / "chatgpt_raw.json"
    if not rf.exists():
        return []
    with open(rf, encoding="utf-8") as f:
        data = json.load(f)
    convs = data.get("conversations", {})
    if isinstance(convs, dict):
        convs_iter = convs.values()
    else:
        convs_iter = convs
    pids = set()
    for c in convs_iter:
        pid = c.get("_project_id") or c.get("gizmo_id")
        if pid and pid.startswith("g-p-"):
            pids.add(pid)
    return sorted(pids)


async def main(raw_dir: Path, profile: str):
    project_ids = _collect_project_ids_from_raw(raw_dir)
    if not project_ids:
        print(f"Nenhum project_id encontrado em {raw_dir}/chatgpt_raw.json")
        return

    print(f"Encontrados {len(project_ids)} project_ids no raw")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            f".storage/chatgpt-profile-{profile}",
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        client = ChatGPTAPIClient(context.request)
        try:
            stats = await download_project_sources(client, project_ids, raw_dir)
            # Save log
            log_path = raw_dir / "project_sources_log.json"
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            print(f"\nLog salvo em {log_path}")
        finally:
            await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download project sources ChatGPT")
    parser.add_argument("raw_dir", nargs="?", default=None)
    parser.add_argument("--profile", default="default")
    args = parser.parse_args()

    if args.raw_dir:
        raw = Path(args.raw_dir)
    else:
        raw = _find_latest_raw()
        if not raw:
            print("ERRO: nenhum raw ChatGPT encontrado")
            sys.exit(1)
        print(f"Usando raw: {raw}")

    asyncio.run(main(raw, args.profile))
