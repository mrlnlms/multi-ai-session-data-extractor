"""Read-only Project detail capture without refreshing conversations or account memory.

Usage: PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.capture_project_settings --account default
"""

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from src.account_bindings import load_account_bindings
from src.account_catalog import LifecycleStatus, load_account_catalog
from src.platforms.chatgpt.extractor.api_client import ChatGPTAPIClient
from src.platforms.chatgpt.extractor.auth import get_profile_dir
from src.platforms.chatgpt.extractor.project_settings import capture_project_settings


async def _capture(account: str, raw_base: Path) -> dict:
    catalog = load_account_catalog(Path("data/accounts/catalog.json"))
    bindings = load_account_bindings()
    matches = [record for record in catalog.records if record.platform == "ChatGPT"
               and record.lifecycle_status is LifecycleStatus.ACTIVE
               and (binding := bindings.get(record.account_id)) is not None
               and binding.profile_key == account]
    if len(matches) != 1:
        raise ValueError("Expected exactly one active ChatGPT account bound to this profile")
    raw_root = raw_base / f"account-{matches[0].account_id}"
    profile = get_profile_dir(account)
    if not profile.is_dir():
        raise FileNotFoundError(f"ChatGPT profile missing: {profile}")
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile), headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = await context.new_page()
            await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)
            client = ChatGPTAPIClient(context.request, page=page)
            return await capture_project_settings(client, raw_root)
        finally:
            await context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture ChatGPT Project settings (read-only)")
    parser.add_argument("--account", required=True, help="Technical ChatGPT profile key")
    parser.add_argument("--raw-base", type=Path, default=Path("data/raw/ChatGPT"))
    args = parser.parse_args()
    result = asyncio.run(_capture(args.account, args.raw_base))
    print(f"Projects: {result['projects_captured']}/{result['projects_targeted']} captured; "
          f"discovery_succeeded={result['discovery_succeeded']}; errors={len(result['errors'])}")
    for error in result["errors"]:
        print(f"  {error['stage']}: {error.get('project_id', '-')} ({error['error_type']})")


if __name__ == "__main__":
    main()
