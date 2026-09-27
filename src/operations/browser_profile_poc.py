"""Read-only shared-browser experiment outside the canonical capture pipeline.

Without --profile-id, the operation uses the original isolated Foton PoC
profile. With --profile-id, it resolves a durable group and its machine-local
binding; paths may point at an existing profile without copying its cookies.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

from playwright.async_api import async_playwright

from src.account_catalog import load_account_catalog
from src.browser_profile_catalog import DEFAULT_CATALOG_PATH, load_browser_profile_catalog
from src.browser_profile_runtime import (
    BrowserProfileTarget, open_browser_profile, resolve_account_browser_profile,
    resolve_browser_profile,
)
from src.local_browser_profiles import DEFAULT_LOCAL_PATH, load_local_browser_profiles
from src.platforms.gemini.extractor.api_client import RPC_LIST
from src.platforms.gemini.extractor.batchexecute import call_rpc, load_session
from src.platforms.notebooklm.extractor.api_client import RPC_LIST_NOTEBOOKS
from src.platforms.notebooklm.extractor.batchexecute import (
    call_rpc as notebooklm_call_rpc,
    load_session as notebooklm_load_session,
)


POC_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "multi-ai-session-data-extractor/browser-profile-poc-shared"))
SITES = (
    ("ChatGPT", "https://chatgpt.com/"),
    ("Gemini", "https://gemini.google.com/app"),
)


def _target(args: argparse.Namespace) -> BrowserProfileTarget:
    if args.profile_id:
        return resolve_browser_profile(
            load_browser_profile_catalog(args.groups_path),
            load_local_browser_profiles(args.local_path),
            profile_id=args.profile_id, storage_root=args.storage_root,
        )
    return BrowserProfileTarget(POC_ID, args.storage_root / "browser-profile-poc-shared", "chromium")


async def _open(target: BrowserProfileTarget, storage_root: Path) -> None:
    target.path.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        async with open_browser_profile(playwright, target, storage_root=storage_root, headless=False) as context:
            for name, url in SITES:
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                except Exception as exc:
                    print(f"{name}: navigation did not finish ({type(exc).__name__}); inspect the visible tab")
            print("Use the visible tabs to sign in and confirm both account identities.")
            print("Close the browser window when finished; no archive data will be written.")
            await context.wait_for_event("close", timeout=0)


async def _check(target: BrowserProfileTarget, storage_root: Path) -> None:
    async with async_playwright() as playwright:
        async with open_browser_profile(playwright, target, storage_root=storage_root, headless=False) as context:
            page = await context.new_page()
            await page.goto(SITES[0][1], wait_until="domcontentloaded", timeout=60_000)
            try:
                chatgpt = await page.evaluate(
                    """async () => {
                        const response = await fetch('/api/auth/session', {credentials: 'include'});
                        if (!response.ok) return {status: response.status, active: false};
                        const body = await response.json();
                        return {status: response.status, active: Boolean(body.accessToken)};
                    }"""
                )
                print(f"ChatGPT authenticated session: {chatgpt['active']} (HTTP {chatgpt['status']})")
            except Exception as exc:
                print(f"ChatGPT read inconclusive: {type(exc).__name__}")

            gemini_page = await context.new_page()
            await gemini_page.goto(SITES[1][1], wait_until="domcontentloaded", timeout=60_000)
            try:
                session = await load_session(context)
                data = await call_rpc(context, session, RPC_LIST, [], reqid=1)
                valid = isinstance(data, list) and len(data) > 2 and isinstance(data[2], list)
                print(f"Gemini authenticated conversation-list shape: {valid}")
            except Exception as exc:
                print(f"Gemini read inconclusive: {type(exc).__name__}")
            print("Confirm the selected account in each visible site tab before using this result.")
            print("Close the browser window when finished.")
            await context.wait_for_event("close", timeout=0)


async def _check_notebooklm(target: BrowserProfileTarget, storage_root: Path) -> None:
    async with async_playwright() as playwright:
        async with open_browser_profile(playwright, target, storage_root=storage_root, headless=False) as context:
            page = await context.new_page()
            await page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded", timeout=60_000)
            try:
                session = await notebooklm_load_session(context)
                data = await notebooklm_call_rpc(
                    context, session, RPC_LIST_NOTEBOOKS, [None, 1, None, [2]], reqid=1,
                )
                valid = isinstance(data, list) and bool(data) and isinstance(data[0], list)
                count = len(data[0]) if valid else None
                print(f"NotebookLM authenticated listing: {valid}; notebook count: {count}")
            except Exception as exc:
                print(f"NotebookLM read inconclusive: {type(exc).__name__}")
            print("Check the selected account in the visible tab, then close the browser window.")
            await context.wait_for_event("close", timeout=0)


async def _sample(target: BrowserProfileTarget, storage_root: Path) -> None:
    """Attempt a native content read per source without writing raw data."""
    from src.platforms.chatgpt.extractor.api_client import ChatGPTAPIClient
    from src.platforms.chatgpt.extractor.discovery import discover_all
    from src.platforms.gemini.extractor.api_client import GeminiAPIClient
    from src.platforms.notebooklm.extractor.api_client import NotebookLMClient

    async with async_playwright() as playwright:
        async with open_browser_profile(playwright, target, storage_root=storage_root, headless=False) as context:
            page = await context.new_page()
            await page.goto(SITES[0][1], wait_until="domcontentloaded", timeout=60_000)
            client = ChatGPTAPIClient(context.request, page=page)
            conversations, _ = await discover_all(client, page=page)
            fetched = False
            if conversations:
                body = await client.fetch_conversation(conversations[0].id)
                fetched = isinstance(body, dict) and bool(body)
            print(
                f"ChatGPT client: discovery_result={len(conversations)}; "
                f"sample_fetch={fetched}; zero is not proof of an empty account"
            )

        async with open_browser_profile(playwright, target, storage_root=storage_root, headless=True) as context:
            session = await load_session(context)
            client = GeminiAPIClient(context, session)
            conversations = await client.list_conversations()
            fetched = False
            if conversations:
                body = await client.fetch_conversation(conversations[0]["uuid"])
                fetched = isinstance(body, dict) and body.get("raw") is not None
            print(f"Gemini client: listed={len(conversations)}; sample_fetch={fetched}")

        async with open_browser_profile(playwright, target, storage_root=storage_root, headless=True) as context:
            session = await notebooklm_load_session(context)
            client = NotebookLMClient(context, session, hl="pt-BR")
            notebooks = await client.list_notebooks()
            fetched = False
            if notebooks:
                metadata = await client.fetch_metadata(notebooks[0]["uuid"])
                fetched = metadata is not None
            print(f"NotebookLM client: listed={len(notebooks)}; sample_fetch={fetched}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("open", "check", "notebooklm", "sample"))
    parser.add_argument("--profile-id", help="resolve a browser group and its local binding")
    parser.add_argument("--verify-account-map", action="store_true",
                        help="require ChatGPT, Gemini and NotebookLM account UUIDs in this group")
    parser.add_argument("--accounts-path", type=Path, default=Path("data/accounts/catalog.json"),
                        help=argparse.SUPPRESS)
    parser.add_argument("--groups-path", type=Path, default=DEFAULT_CATALOG_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--local-path", type=Path, default=DEFAULT_LOCAL_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--storage-root", type=Path, default=Path(".storage"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    target = _target(args)
    if args.verify_account_map:
        if args.mode != "sample" or not args.profile_id:
            parser.error("--verify-account-map requires sample and --profile-id")
        accounts = load_account_catalog(args.accounts_path)
        groups = load_browser_profile_catalog(args.groups_path)
        local = load_local_browser_profiles(args.local_path)
        group = groups.get(args.profile_id)
        assert group is not None  # _target already validated the group.
        for platform in ("ChatGPT", "Gemini", "NotebookLM"):
            members = [
                account.account_id for account in accounts.records
                if account.platform == platform and account.account_id in group.account_ids
            ]
            if len(members) != 1:
                raise ValueError(f"Expected one {platform} account in browser group")
            account_target = resolve_account_browser_profile(
                accounts, groups, local, account_id=members[0], storage_root=args.storage_root,
            )
            if account_target != target:
                raise ValueError(f"Browser target mismatch for {platform}")
    action = {
        "open": _open,
        "check": _check,
        "notebooklm": _check_notebooklm,
        "sample": _sample,
    }[args.mode]
    asyncio.run(action(target, args.storage_root))


if __name__ == "__main__":
    main()
