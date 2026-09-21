"""Preview-first account catalog, binding, and authentication operations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from src.account_bindings import (
    DEFAULT_BINDINGS_PATH, AccountBinding, load_account_bindings,
    set_account_binding, write_account_bindings_atomic,
)
from src.account_catalog import LifecycleStatus, load_account_catalog, serialize_account_catalog, write_account_catalog_atomic
from src.account_service import create_account, set_account_metadata, set_lifecycle
from src.auth_health import (
    DEFAULT_HEALTH_PATH, AuthEvidenceMethod, AuthObservation, AuthStatus,
    load_auth_health, set_auth_observation, write_auth_health_atomic,
)
from src.auth_probes import check_account_auth


PRESERVATION_NOTICE = "Identity and preserved data will not be deleted."


def check_and_optionally_persist_auth(account_id: str, *, catalog_path: Path, bindings_path: Path,
                                      health_path: Path, storage_root: Path, apply: bool):
    observation = check_account_auth(account_id, catalog=load_account_catalog(catalog_path),
                                     bindings=load_account_bindings(bindings_path), storage_root=storage_root)
    if apply:
        before = load_auth_health(health_path)
        write_auth_health_atomic(health_path, set_auth_observation(before, observation), expected_before=before)
    return observation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage account identities without physical deletion.")
    parser.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"), help=argparse.SUPPRESS)
    parser.add_argument("--bindings-path", type=Path, default=DEFAULT_BINDINGS_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--health-path", type=Path, default=DEFAULT_HEALTH_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--storage-root", type=Path, default=Path(".storage"), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    create = sub.add_parser("create")
    create.add_argument("--platform", required=True)
    create.add_argument("--display-name")
    create.add_argument("--email")
    create.add_argument("--apply", action="store_true")
    edit = sub.add_parser("edit")
    edit.add_argument("account_id")
    edit.add_argument("--display-name")
    edit.add_argument("--email")
    edit.add_argument("--apply", action="store_true")
    lifecycle = sub.add_parser("lifecycle")
    lifecycle.add_argument("account_id")
    lifecycle.add_argument("status", choices=[item.value for item in LifecycleStatus])
    lifecycle.add_argument("--apply", action="store_true")
    bind = sub.add_parser("bind")
    bind.add_argument("account_id")
    bind.add_argument("--profile-key", required=True)
    bind.add_argument("--apply", action="store_true")
    auth = sub.add_parser("auth-check")
    auth.add_argument("account_id")
    auth.add_argument("--apply", action="store_true", help="persist the completed observation")
    confirm = sub.add_parser("auth-confirm", help="record an operator-confirmed visible login")
    confirm.add_argument("account_id")
    confirm.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = datetime.now(timezone.utc)
    catalog = load_account_catalog(args.catalog_path)
    if args.command == "list":
        for item in catalog.records:
            name = item.display_name or ""
            email = item.email or ""
            print(f"{item.account_id}  {item.platform}  {name}  {email}  {item.lifecycle_status.value}")
        return 0
    if args.command == "auth-check":
        result = check_and_optionally_persist_auth(args.account_id, catalog_path=args.catalog_path,
            bindings_path=args.bindings_path, health_path=args.health_path,
            storage_root=args.storage_root, apply=args.apply)
        print(json.dumps({"account_id": result.account_id, "status": result.status.value,
                          "detail": result.detail, "persisted": args.apply}))
        return 0
    if args.command == "auth-confirm":
        record = next((item for item in catalog.records if item.account_id == args.account_id), None)
        if record is None:
            raise ValueError(f"Unknown account_id: {args.account_id}")
        if record.lifecycle_status is not LifecycleStatus.ACTIVE:
            raise ValueError("Only active accounts can be manually confirmed")
        print(f"Preview auth-confirm: {args.health_path}")
        print("Operator confirms the visible account session is authenticated.")
        print(PRESERVATION_NOTICE)
        if not args.apply:
            print("Preview only; pass --apply to write atomically.")
            return 0
        before = load_auth_health(args.health_path)
        observation = AuthObservation(
            args.account_id, AuthStatus.VALID, now,
            "Visible authenticated session confirmed by operator",
            AuthEvidenceMethod.OPERATOR,
        )
        write_auth_health_atomic(
            args.health_path, set_auth_observation(before, observation), expected_before=before,
        )
        print("Applied.")
        return 0
    if args.command == "create":
        change = create_account(
            catalog, platform=args.platform, display_name=args.display_name,
            email=args.email, now=now,
        )
        apply = args.apply
        target, before, after = args.catalog_path, catalog, change.after
    elif args.command == "edit":
        change = set_account_metadata(
            catalog, args.account_id, display_name=args.display_name,
            email=args.email, now=now,
        )
        apply = args.apply
        target, before, after = args.catalog_path, catalog, change.after
    elif args.command == "lifecycle":
        change = set_lifecycle(catalog, args.account_id, LifecycleStatus(args.status), now=now)
        apply = args.apply
        target, before, after = args.catalog_path, catalog, change.after
    else:
        if not any(item.account_id == args.account_id for item in catalog.records):
            raise ValueError(f"Unknown account_id: {args.account_id}")
        before = load_account_bindings(args.bindings_path)
        after = set_account_binding(before, AccountBinding(args.account_id, args.profile_key, now))
        apply = args.apply
        target = args.bindings_path
    print(f"Preview {args.command}: {target}")
    print(PRESERVATION_NOTICE)
    if not apply:
        print("Preview only; pass --apply to write atomically.")
        return 0
    if args.command == "bind":
        write_account_bindings_atomic(target, after, expected_before=before)
    else:
        write_account_catalog_atomic(target, after, expected_before=before)
    print("Applied.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
