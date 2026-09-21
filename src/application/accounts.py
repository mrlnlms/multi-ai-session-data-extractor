"""UI-neutral account action previews and explicitly confirmed outcomes."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from src.account_catalog import LifecycleStatus
from src.accounts import AccountState
from src.operations.accounts import PRESERVATION_NOTICE, main as account_cli
from src.platforms.registry import PLATFORM_ACCOUNT_CAPABILITIES, PLATFORM_ACCOUNT_METADATA
from src.workflows.account_sync import (
    AccountSyncPlan, execute_account_sync, plan_account_sync, record_successful_sync_auth,
)

DEFAULT_CATALOG_PATH = Path("data/accounts/catalog.json")

@dataclass(frozen=True)
class AccountActionView:
    action: str
    account_id: str | None
    confirmation: str
    enabled: bool
    command: str | None = None

@dataclass(frozen=True)
class AccountActionOutcome:
    ok: bool
    message: str

def account_actions(account: AccountState) -> tuple[AccountActionView, ...]:
    active = account.lifecycle_status is LifecycleStatus.ACTIVE
    capability = PLATFORM_ACCOUNT_CAPABILITIES.get(account.platform)
    command = None
    if capability:
        source = "claude_ai" if account.platform == "Claude.ai" else account.platform.lower()
        profile_key = account.key
        metadata = PLATFORM_ACCOUNT_METADATA[account.platform]
        if account.evidence.profile_path is not None:
            name = account.evidence.profile_path.name
            if name.startswith(metadata.profile_prefix):
                profile_key = name[len(metadata.profile_prefix):]
        command = f"PYTHONPATH=. .venv/bin/python -m src.platforms.{source}.commands.login {capability.login_argument} {profile_key}"
    return tuple(AccountActionView(name, account.account_id, PRESERVATION_NOTICE,
        True if name in {"lifecycle", "bind"} else active, command if name == "login" else None)
        for name in ("lifecycle", "bind", "auth-check", "auth-confirm", "sync", "login"))

def add_account_action(*, platform: str, display_name: str | None = None,
                       email: str | None = None, confirmed: bool,
                       catalog_path: Path = DEFAULT_CATALOG_PATH) -> AccountActionOutcome:
    args = ["--catalog-path", str(catalog_path), "create", "--platform", platform]
    if display_name is not None: args.extend(["--display-name", display_name])
    if email is not None: args.extend(["--email", email])
    if confirmed: args.append("--apply")
    try:
        account_cli(args)
        return AccountActionOutcome(True, "Account created." if confirmed else "Preview ready. " + PRESERVATION_NOTICE)
    except ValueError as exc:
        return AccountActionOutcome(False, str(exc))

def lifecycle_action(account_id: str, status: LifecycleStatus, *, confirmed: bool,
                     catalog_path: Path = DEFAULT_CATALOG_PATH) -> AccountActionOutcome:
    args = ["--catalog-path", str(catalog_path), "lifecycle", account_id, status.value]
    if confirmed: args.append("--apply")
    try:
        account_cli(args)
        return AccountActionOutcome(True, "Lifecycle updated." if confirmed else "Preview ready. " + PRESERVATION_NOTICE)
    except ValueError as exc:
        return AccountActionOutcome(False, str(exc))

def bind_action(account_id: str, profile_key: str, *, confirmed: bool,
                catalog_path: Path = DEFAULT_CATALOG_PATH,
                bindings_path: Path = Path(".storage/account-bindings.json")) -> AccountActionOutcome:
    args = ["--catalog-path", str(catalog_path), "--bindings-path", str(bindings_path), "bind", account_id, "--profile-key", profile_key]
    if confirmed: args.append("--apply")
    try:
        account_cli(args)
        return AccountActionOutcome(True, "Profile binding updated." if confirmed else "Preview ready. " + PRESERVATION_NOTICE)
    except ValueError as exc:
        return AccountActionOutcome(False, str(exc))

def auth_check_action(account_id: str, *, confirmed: bool,
                      catalog_path: Path = DEFAULT_CATALOG_PATH,
                      bindings_path: Path = Path(".storage/account-bindings.json"),
                      health_path: Path = Path(".storage/account-health.json"),
                      storage_root: Path = Path(".storage")) -> AccountActionOutcome:
    if not confirmed:
        return AccountActionOutcome(True, "Live read preview ready. " + PRESERVATION_NOTICE)
    try:
        account_cli(["--catalog-path", str(catalog_path), "--bindings-path", str(bindings_path), "--health-path", str(health_path), "--storage-root", str(storage_root), "auth-check", account_id, "--apply"])
        return AccountActionOutcome(True, "Login health checked and stored locally.")
    except ValueError as exc:
        return AccountActionOutcome(False, str(exc))

def auth_confirm_action(account_id: str, *, confirmed: bool,
                        catalog_path: Path = DEFAULT_CATALOG_PATH,
                        health_path: Path = Path(".storage/account-health.json")) -> AccountActionOutcome:
    if not confirmed:
        return AccountActionOutcome(True, "Manual login confirmation preview ready. " + PRESERVATION_NOTICE)
    try:
        account_cli(["--catalog-path", str(catalog_path), "--health-path", str(health_path),
                     "auth-confirm", account_id, "--apply"])
        return AccountActionOutcome(True, "Visible login recorded as operator-confirmed.")
    except ValueError as exc:
        return AccountActionOutcome(False, str(exc))

def sync_action(account_id: str, *, confirmed: bool, runner=execute_account_sync,
                catalog_path: Path = DEFAULT_CATALOG_PATH,
                bindings_path: Path = Path(".storage/account-bindings.json"),
                health_path: Path = Path(".storage/account-health.json"),
                storage_root: Path = Path(".storage")) -> AccountActionOutcome:
    try:
        plan = plan_account_sync(account_id, catalog_path=catalog_path, bindings_path=bindings_path,
                                 health_path=health_path, storage_root=storage_root)
        if not confirmed:
            return AccountActionOutcome(True, "Sync preview ready. " + PRESERVATION_NOTICE)
        rc, detail = runner(plan)
        if rc == 0:
            record_successful_sync_auth(plan.account_id, health_path=health_path)
        return AccountActionOutcome(rc == 0, "Sync and parse completed." if rc == 0 else detail)
    except ValueError as exc:
        return AccountActionOutcome(False, str(exc))

def sync_preview(account_id: str, **paths) -> AccountSyncPlan:
    return plan_account_sync(account_id, **paths)
