"""Preview-first management of durable browser groups and local profile setup."""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from src.account_catalog import load_account_catalog
from src.browser_profile_catalog import (
    DEFAULT_CATALOG_PATH, load_browser_profile_catalog, write_browser_profile_catalog_atomic,
)
from src.browser_profile_service import (
    assign_account, create_browser_profile, unassign_account,
)
from src.browser_profile_runtime import open_browser_profile, resolve_browser_profile
from src.local_browser_profiles import (
    DEFAULT_LOCAL_PATH, browser_profile_path, load_local_browser_profiles,
    set_local_browser_profile, write_local_browser_profiles_atomic,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups-path", type=Path, default=DEFAULT_CATALOG_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--accounts-path", type=Path, default=Path("data/accounts/catalog.json"), help=argparse.SUPPRESS)
    parser.add_argument("--local-path", type=Path, default=DEFAULT_LOCAL_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--storage-root", type=Path, default=Path(".storage"), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    create = sub.add_parser("create")
    create.add_argument("--display-name", required=True)
    create.add_argument("--email")
    create.add_argument("--profile-id", help="UUID to reuse the exact ID shown by a preview")
    create.add_argument("--apply", action="store_true")
    assign = sub.add_parser("assign")
    assign.add_argument("profile_id")
    assign.add_argument("account_id")
    assign.add_argument("--apply", action="store_true")
    unassign = sub.add_parser("unassign")
    unassign.add_argument("profile_id")
    unassign.add_argument("account_id")
    unassign.add_argument("--apply", action="store_true")
    initialize = sub.add_parser("local-init")
    initialize.add_argument("profile_id")
    initialize.add_argument("--channel", choices=("chromium", "chrome"), default="chromium")
    initialize.add_argument("--apply", action="store_true")
    existing = sub.add_parser("local-bind", help="use an existing directory inside .storage without copying it")
    existing.add_argument("profile_id")
    existing.add_argument("--directory", required=True, help="path relative to --storage-root")
    existing.add_argument("--channel", choices=("chromium", "chrome"), required=True)
    existing.add_argument("--apply", action="store_true")
    open_site = sub.add_parser("open-site", help="open one website in a configured browser group")
    open_site.add_argument("profile_id")
    open_site.add_argument("url", help="HTTPS website for one manual login")
    return parser


async def _open_site(profile_id: str, url: str, *, groups_path: Path,
                     local_path: Path, storage_root: Path) -> None:
    from playwright.async_api import async_playwright

    target = resolve_browser_profile(
        load_browser_profile_catalog(groups_path),
        load_local_browser_profiles(local_path),
        profile_id=profile_id, storage_root=storage_root,
    )
    async with async_playwright() as playwright:
        async with open_browser_profile(
            playwright, target, storage_root=storage_root, headless=False,
        ) as context:
            page = context.pages[0] if context.pages else await context.new_page()
            for extra in list(context.pages):
                if extra != page:
                    await extra.close()
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            print("Complete the login in this one website, then close the browser window.")
            await context.wait_for_event("close", timeout=0)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalog = load_browser_profile_catalog(args.groups_path)
    local = load_local_browser_profiles(args.local_path)
    if args.command == "open-site":
        parsed = urlsplit(args.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("open-site requires a valid HTTPS website URL")
        asyncio.run(_open_site(
            args.profile_id, args.url, groups_path=args.groups_path,
            local_path=args.local_path, storage_root=args.storage_root,
        ))
        return 0
    if args.command == "list":
        accounts = load_account_catalog(args.accounts_path)
        account_by_id = {item.account_id: item for item in accounts.records}
        for group in catalog.records:
            config = local.get(group.profile_id)
            path = browser_profile_path(args.storage_root, group.profile_id, local)
            local_status = "present" if path.is_dir() else "not configured"
            channel = config.channel if config else "—"
            print(f"{group.profile_id}  {group.display_name}  {group.email or '—'}  "
                  f"accounts={len(group.account_ids)}  local={local_status}  channel={channel}")
            for account_id in group.account_ids:
                account = account_by_id.get(account_id)
                label = account.platform if account is not None else "catalog record missing"
                print(f"  {label}  {account_id}")
        return 0

    now = datetime.now(timezone.utc)
    if args.command == "create":
        selected_id = uuid.UUID(args.profile_id) if args.profile_id else uuid.uuid4()
        after, profile_id = create_browser_profile(
            catalog, display_name=args.display_name, email=args.email, now=now,
            profile_id_factory=lambda: selected_id,
        )
        print(f"Preview create group: {args.display_name} ({profile_id})")
        if not args.apply and not args.profile_id:
            print(f"Use --profile-id {profile_id} with --apply to keep this exact ID.")
    elif args.command == "assign":
        accounts = load_account_catalog(args.accounts_path)
        after = assign_account(
            catalog, accounts, profile_id=args.profile_id, account_id=args.account_id, now=now,
        )
        print(f"Preview assign account {args.account_id} to group {args.profile_id}")
    elif args.command == "unassign":
        after = unassign_account(
            catalog, profile_id=args.profile_id, account_id=args.account_id, now=now,
        )
        print(f"Preview unassign account {args.account_id} from group {args.profile_id}")
    else:
        after_local = set_local_browser_profile(
            local, catalog, profile_id=args.profile_id, channel=args.channel,
            storage_root=args.storage_root,
            directory=args.directory if args.command == "local-bind" else None,
            adopt_existing=args.command == "local-bind",
        )
        path = browser_profile_path(args.storage_root, args.profile_id, after_local)
        print(f"Preview local profile: {path} ({args.channel})")

    if not args.apply:
        print("Preview only; pass --apply to write. No login or capture is performed.")
        return 0
    if args.command in {"local-init", "local-bind"}:
        if args.command == "local-init":
            path.mkdir(parents=True, exist_ok=True)
        write_local_browser_profiles_atomic(args.local_path, after_local, expected_before=local)
    else:
        write_browser_profile_catalog_atomic(args.groups_path, after, expected_before=catalog)
    print("Applied. No login or capture was performed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
