"""Preview-first selective web sync resolved from an immutable account UUID."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone

from src.account_bindings import DEFAULT_BINDINGS_PATH, load_account_bindings
from src.account_catalog import LifecycleStatus, load_account_catalog
from src.accounts import ACCOUNT_ID_ENV, account_command_argument
from src.auth_health import (
    AuthEvidenceMethod, AuthObservation, AuthStatus, DEFAULT_HEALTH_PATH,
    load_auth_health, set_auth_observation, write_auth_health_atomic,
)
from src.platforms.registry import PLATFORM_ACCOUNT_METADATA, PLATFORM_COMMAND_PACKAGES
from src.workflows.execution import run_commands


@dataclass(frozen=True)
class AccountSyncPlan:
    account_id: str
    platform: str
    commands: tuple[tuple[str, ...], ...]
    warning: str | None = None


def plan_account_sync(
    account_id: str,
    *,
    catalog_path: Path = Path("data/accounts/catalog.json"),
    bindings_path: Path = DEFAULT_BINDINGS_PATH,
    health_path: Path = DEFAULT_HEALTH_PATH,
    storage_root: Path = Path(".storage"),
) -> AccountSyncPlan:
    catalog = load_account_catalog(catalog_path)
    record = next((item for item in catalog.records if item.account_id == account_id), None)
    if record is None:
        raise ValueError(f"Unknown account_id: {account_id}")
    if record.lifecycle_status is not LifecycleStatus.ACTIVE:
        raise ValueError(f"Account lifecycle prevents sync: {record.lifecycle_status.value}")
    binding = load_account_bindings(bindings_path).get(account_id)
    if binding is None:
        raise ValueError("Account has no local profile binding")
    metadata = PLATFORM_ACCOUNT_METADATA[record.platform]
    profile = storage_root / f"{metadata.profile_prefix}{binding.profile_key}"
    if record.platform == "Perplexity" and binding.profile_key == "default" and (
        storage_root / "perplexity-profile"
    ).is_dir():
        profile = storage_root / "perplexity-profile"
    if not profile.is_dir():
        raise ValueError("Bound local profile is missing")
    observation = load_auth_health(health_path).get(account_id)
    if observation is not None and observation.status in {AuthStatus.EXPIRED, AuthStatus.MISSING}:
        raise ValueError(f"Authentication status prevents sync: {observation.status.value}")
    warning = None
    if observation is None or observation.status in {AuthStatus.UNKNOWN, AuthStatus.ERROR}:
        warning = "Authentication is unknown; sync may fail. Use --check-auth for a live read first."
    flag, key = account_command_argument(record.platform, binding.profile_key)
    package = PLATFORM_COMMAND_PACKAGES[record.platform]
    sync = [sys.executable, "-m", f"{package}.sync", flag, key]
    if record.platform == "ChatGPT":
        sync.append("--no-voice-pass")
    parse = [sys.executable, "-m", f"{package}.parse"]
    return AccountSyncPlan(account_id, record.platform, (tuple(sync), tuple(parse)), warning)


def execute_account_sync(plan: AccountSyncPlan, *, runner: Callable = run_commands) -> tuple[int, str]:
    if runner is run_commands:
        return runner(plan.commands, extra_env={ACCOUNT_ID_ENV: plan.account_id})
    return runner(plan.commands)


def record_successful_sync_auth(account_id: str, *, health_path: Path = DEFAULT_HEALTH_PATH) -> None:
    before = load_auth_health(health_path)
    observation = AuthObservation(
        account_id, AuthStatus.VALID, datetime.now(timezone.utc),
        "Authenticated account sync and parse completed", AuthEvidenceMethod.SYNC,
    )
    write_auth_health_atomic(
        health_path, set_auth_observation(before, observation), expected_before=before,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview or run one account sync by immutable UUID.")
    parser.add_argument("account_id")
    parser.add_argument("--apply", action="store_true", help="execute sync and mandatory platform parse")
    parser.add_argument("--check-auth", action="store_true", help="run an explicit live auth read before planning")
    parser.add_argument("--catalog-path", type=Path, default=Path("data/accounts/catalog.json"), help=argparse.SUPPRESS)
    parser.add_argument("--bindings-path", type=Path, default=DEFAULT_BINDINGS_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--health-path", type=Path, default=DEFAULT_HEALTH_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--storage-root", type=Path, default=Path(".storage"), help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.check_auth:
        from src.operations.accounts import check_and_optionally_persist_auth
        check_and_optionally_persist_auth(args.account_id, catalog_path=args.catalog_path,
                                          bindings_path=args.bindings_path, health_path=args.health_path,
                                          storage_root=args.storage_root, apply=args.apply)
    plan = plan_account_sync(args.account_id, catalog_path=args.catalog_path,
                             bindings_path=args.bindings_path, health_path=args.health_path,
                             storage_root=args.storage_root)
    print(f"Account sync preview: {plan.platform}:{plan.account_id}")
    for command in plan.commands:
        print("  " + " ".join(command))
    if plan.warning:
        print("WARNING: " + plan.warning)
    if not args.apply:
        print("Preview only; pass --apply to execute.")
        return 0
    rc, output = execute_account_sync(plan)
    if rc == 0:
        record_successful_sync_auth(plan.account_id, health_path=args.health_path)
    print(output, end="")
    return rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
