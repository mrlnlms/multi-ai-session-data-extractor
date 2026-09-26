"""Read-only, focused capture of Perplexity Project/Space settings."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from src.account_bindings import load_account_bindings
from src.account_catalog import LifecycleStatus, load_account_catalog
from src.platforms.perplexity.extractor.api_client import HOME_URL, PerplexityAPIClient
from src.platforms.perplexity.extractor.auth import get_profile_dir
from src.platforms.perplexity.extractor.project_settings import capture_project_settings


async def _capture(account: str, raw_base: Path) -> dict:
    catalog = load_account_catalog(Path("data/accounts/catalog.json"))
    bindings = load_account_bindings()
    matches = [record for record in catalog.records if record.platform == "Perplexity"
               and record.lifecycle_status is LifecycleStatus.ACTIVE
               and (binding := bindings.get(record.account_id)) is not None
               and binding.profile_key == account]
    if len(matches) != 1:
        raise ValueError("Expected exactly one active Perplexity account bound to this profile")
    raw_root = raw_base / f"account-{matches[0].account_id}"
    profile = get_profile_dir(account)
    if not profile.is_dir():
        raise FileNotFoundError(f"Perplexity profile missing: {profile}")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile), headless=False, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_https_errors=True, bypass_csp=True,
        )
        try:
            page = await context.new_page()
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            client = PerplexityAPIClient(context, page)
            return await capture_project_settings(client, raw_root)
        finally:
            await context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default="default", help="Technical Perplexity profile key")
    parser.add_argument("--raw-base", type=Path, default=Path("data/raw/Perplexity"))
    args = parser.parse_args()
    result = asyncio.run(_capture(args.account, args.raw_base))
    print(f"Projects: {result['captured']}/{result['targeted']} settings captured; "
          f"discovery_succeeded={result['discovery_succeeded']}; "
          f"nonempty_instructions={result['nonempty_instructions']}; "
          f"errors={len(result['errors'])}")
    for error in result["errors"]:
        print(f"  {error['stage']}: {error.get('space_uuid', '-')} ({error['error_type']})")
    if not result["discovery_succeeded"] or result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
