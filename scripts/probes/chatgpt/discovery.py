"""Executa descoberta ChatGPT sem escrita de raw e preserva somente métricas.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/dev/probe-chatgpt-discovery.py
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from src.extractors.chatgpt.api_client import ChatGPTAPIClient
from src.extractors.chatgpt.auth import get_profile_dir
from src.extractors.chatgpt.discovery import discover_all


OUTPUT_DIR = Path(".storage/chatgpt-probe")


async def main() -> None:
    result: dict = {"started_at": datetime.now(timezone.utc).isoformat()}
    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(get_profile_dir()),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = await context.new_page()
            await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(5_000)
            client = ChatGPTAPIClient(context.request, page=page)
            metas, project_names = await discover_all(client, page=page)
            result.update({
                "status": "ok",
                "conversations": len(metas),
                "projects": len(project_names),
                "project_conversations": sum(1 for meta in metas if meta.project_id),
            })
            await context.close()
    except Exception as exc:
        result.update({"status": "error", "error_type": type(exc).__name__, "error": str(exc)})
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / (
        "discovery-probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    print(output_path)


if __name__ == "__main__":
    asyncio.run(main())
