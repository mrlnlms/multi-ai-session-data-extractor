"""Read-only account inventory backed by the application state."""

from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

from src.accounts import AccountState
from src.application.platforms import PlatformState
from src.account_catalog import LifecycleStatus
from src.application.accounts import (
    account_actions, add_account_action, auth_check_action, auth_confirm_action, bind_action,
    lifecycle_action, sync_action,
)
from src.application.browser_profiles import (
    assign_browser_profile_action, browser_profile_rows, create_browser_profile_action,
    initialize_browser_profile_action,
)
from src.browser_profile_catalog import load_browser_profile_catalog
from src.platforms.registry import WEB_PLATFORMS


def _present(value: bool) -> str:
    return "Present" if value else "—"


def _authentication_label(value: str, method: str | None = None) -> str:
    labels = {
        "unknown": "Unknown (not checked)",
        "not_configured": "Not configured",
    }
    label = labels.get(value, value.replace("_", " ").title())
    return f"{label} — {method}" if method else label


def _lifecycle_label(account: AccountState) -> str:
    if account.lifecycle_status is None:
        return "Unclassified"
    return account.lifecycle_status.value.title()


def _archive_label(account: AccountState) -> str:
    evidence = account.evidence
    if evidence.historical_present:
        return "Historical archive"
    has_data = evidence.raw_present or evidence.merged_present
    if not has_data:
        return "No local data"
    if not evidence.profile_present:
        return "Preserved data without profile"
    return "Data with local profile"


def _account_rows(states: list[PlatformState]) -> list[dict[str, object]]:
    """Build presentation rows without rediscovering account storage."""
    rows: list[dict[str, object]] = []
    for state in states:
        for account in state.accounts:
            evidence = account.evidence
            rows.append(
                {
                    "Platform": state.name,
                    "Account": account.label or f"{state.name} · {account.account_id or account.key}",
                    "Account ID": account.account_id or "—",
                    "Lifecycle": _lifecycle_label(account),
                    "Registry": _present(evidence.registry_present),
                    "Profile": _present(evidence.profile_present),
                    "Raw": _present(evidence.raw_present),
                    "Merged": _present(evidence.merged_present),
                    "Historical": _present(evidence.historical_present),
                    "Authentication": _authentication_label(account.authentication, account.authentication_method),
                    "Archive": _archive_label(account),
                }
            )
    return rows


def _actionable_accounts(states: list[PlatformState]) -> list[AccountState]:
    """Return only catalog identities that can back explicit account actions."""
    return [
        account
        for state in states
        for account in state.accounts
        if account.account_id is not None and account.lifecycle_status is not None
    ]


def _render_browser_profiles(states: list[PlatformState]) -> None:
    st.subheader("Browser profiles — prototype")
    st.caption(
        "A browser group organizes platform accounts and can be restored with DVC. "
        "Its local directory and cookies stay on this machine. Current login and sync "
        "still use the existing per-account profiles."
    )
    groups = load_browser_profile_catalog()
    rows = browser_profile_rows()
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No browser groups have been created.")

    with st.expander("1. Create browser group"):
        name = st.text_input("Group name", key="browser_group_name")
        email = st.text_input("Group e-mail (optional)", key="browser_group_email")
        if st.button("Preview browser group", key="browser_group_preview"):
            profile_id = str(uuid.uuid4())
            outcome = create_browser_profile_action(
                profile_id=profile_id, display_name=name, email=email or None,
                confirmed=False,
            )
            if outcome.ok:
                st.session_state["browser_group_pending"] = (profile_id, name, email or None)
            else:
                st.session_state.pop("browser_group_pending", None)
                st.error(outcome.message)
        pending = st.session_state.get("browser_group_pending")
        if pending:
            st.info(f"Create {pending[1]} with ID {pending[0]}. No browser login will occur.")
            confirmed = st.checkbox("Confirm browser group", key="browser_group_confirm")
            if st.button("Create browser group", disabled=not confirmed, key="browser_group_apply"):
                outcome = create_browser_profile_action(
                    profile_id=pending[0], display_name=pending[1], email=pending[2],
                    confirmed=True,
                )
                (st.success if outcome.ok else st.error)(outcome.message)
                if outcome.ok:
                    st.session_state.pop("browser_group_pending", None)

    if not groups.records:
        return
    group_options = [item.profile_id for item in groups.records]
    group_names = {item.profile_id: item.display_name for item in groups.records}
    assigned_ids = {account_id for item in groups.records for account_id in item.account_ids}
    candidates = [item for item in _actionable_accounts(states) if item.account_id not in assigned_ids]
    with st.expander("2. Associate an account"):
        if candidates:
            profile_id = st.selectbox("Browser group", group_options,
                                      format_func=lambda value: group_names[value], key="browser_assign_group")
            account = st.selectbox("Platform account", candidates,
                                   format_func=lambda item: f"{item.platform} · {item.label or item.key}",
                                   key="browser_assign_account")
            if st.button("Preview association", key="browser_assign_preview"):
                outcome = assign_browser_profile_action(
                    profile_id=profile_id, account_id=account.account_id, confirmed=False,
                )
                if outcome.ok:
                    st.session_state["browser_assign_pending"] = (profile_id, account.account_id)
                else:
                    st.session_state.pop("browser_assign_pending", None)
                    st.error(outcome.message)
            pending = st.session_state.get("browser_assign_pending")
            if pending:
                st.info(f"Associate account {pending[1]} with {group_names.get(pending[0], pending[0])}.")
                confirmed = st.checkbox("Confirm association", key="browser_assign_confirm")
                if st.button("Associate account", disabled=not confirmed, key="browser_assign_apply"):
                    outcome = assign_browser_profile_action(
                        profile_id=pending[0], account_id=pending[1], confirmed=True,
                    )
                    (st.success if outcome.ok else st.error)(outcome.message)
                    if outcome.ok:
                        st.session_state.pop("browser_assign_pending", None)
        else:
            st.caption("No unassigned catalogued accounts are available.")

    with st.expander("3. Prepare local browser directory"):
        profile_id = st.selectbox("Group to prepare", group_options,
                                  format_func=lambda value: group_names[value], key="browser_init_group")
        channel = st.selectbox("Browser", ("chromium", "chrome"), key="browser_init_channel")
        if st.button("Preview local profile", key="browser_init_preview"):
            outcome = initialize_browser_profile_action(
                profile_id=profile_id, channel=channel, confirmed=False,
            )
            if outcome.ok:
                st.session_state["browser_init_pending"] = (profile_id, channel)
            else:
                st.session_state.pop("browser_init_pending", None)
                st.error(outcome.message)
        pending = st.session_state.get("browser_init_pending")
        if pending:
            st.info(f"Create an empty local {pending[1]} directory for {group_names.get(pending[0], pending[0])}.")
            confirmed = st.checkbox("Confirm local directory", key="browser_init_confirm")
            if st.button("Prepare local profile", disabled=not confirmed, key="browser_init_apply"):
                outcome = initialize_browser_profile_action(
                    profile_id=pending[0], channel=pending[1], confirmed=True,
                )
                (st.success if outcome.ok else st.error)(outcome.message)
                if outcome.ok:
                    st.session_state.pop("browser_init_pending", None)


def render(states: list[PlatformState]) -> None:
    st.title("Accounts")
    st.caption(
        "Read-only local inventory. Lifecycle is an explicit archival decision; "
        "authentication and local evidence are reported independently."
    )
    with st.expander("Add account"):
        platform_name = st.selectbox("Platform", sorted(WEB_PLATFORMS), key="account_add_platform")
        display_name = st.text_input("Display name (optional)", key="account_add_name")
        email = st.text_input("E-mail (optional)", key="account_add_email")
        if st.button("Preview add account", key="account_add_preview"):
            st.session_state["account_add_pending"] = (platform_name, display_name, email)
        pending = st.session_state.get("account_add_pending")
        if pending:
            st.warning("Identity and preserved data will not be deleted.")
            confirmed = st.checkbox("I confirm this account catalog change", key="account_add_confirm")
            if st.button("Apply add account", disabled=not confirmed, key="account_add_apply"):
                outcome = add_account_action(
                    platform=pending[0], display_name=pending[1] or None,
                    email=pending[2] or None, confirmed=True,
                )
                (st.success if outcome.ok else st.error)(outcome.message)

    accounts = [account for state in states for account in state.accounts]
    with_data = [
        account
        for account in accounts
        if (
            account.evidence.raw_present
            or account.evidence.merged_present
            or account.evidence.historical_present
        )
    ]
    preserved_without_profile = [
        account
        for account in with_data
        if not account.evidence.profile_present
    ]

    cols = st.columns(4)
    cols[0].metric("Observable accounts", len(accounts))
    cols[1].metric("With local data", len(with_data))
    cols[2].metric(
        "With browser profile",
        sum(account.evidence.profile_present for account in accounts),
    )
    cols[3].metric("Preserved without profile", len(preserved_without_profile))

    lifecycle_order = ("Active", "Disabled", "Historical", "Unclassified")
    lifecycle_counts = {
        label: sum(_lifecycle_label(account) == label for account in accounts)
        for label in lifecycle_order
    }
    st.dataframe(
        pd.DataFrame([
            {"Lifecycle": label, "Accounts": lifecycle_counts[label]}
            for label in lifecycle_order
        ]),
        hide_index=True,
        width="stretch",
    )

    st.info(
        "Authentication evidence is recorded only after an explicit check or operator confirmation. "
        "“Unknown (not checked)” is not a login-health verdict. "
        "Unclassified means evidence exists without a catalog lifecycle decision."
    )

    rows = _account_rows(states)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No account definitions are available.")

    _render_browser_profiles(states)

    st.subheader("Account actions")
    actionable_accounts = _actionable_accounts(states)
    selected = st.selectbox("Account", actionable_accounts,
        format_func=lambda item: f"{item.platform} · {item.key} · {item.account_id}",
        key="account_action_selected") if actionable_accounts else None
    if selected is not None:
        actions = account_actions(selected)
        login = next(item for item in actions if item.action == "login")
        if login.command:
            st.caption("Headed login command (run deliberately in a terminal):")
            st.code(login.command)
        enabled = [item.action for item in actions if item.enabled and item.action != "login"]
        action_name = st.selectbox("Action", enabled, key="account_action_name")
        desired_status = None
        profile_key = None
        if action_name == "lifecycle":
            desired_status = LifecycleStatus(st.selectbox(
                "New lifecycle", [item.value for item in LifecycleStatus], key="account_lifecycle_status"))
        elif action_name == "bind":
            profile_key = st.text_input("Profile key", value=selected.key, key="account_bind_key")
        elif action_name == "auth-confirm":
            st.info("Use only after visibly confirming that this exact account profile is authenticated.")
        if st.button("Preview account action", key="account_action_preview"):
            st.session_state["account_action_pending"] = (selected.account_id, action_name)
        if st.session_state.get("account_action_pending") == (selected.account_id, action_name):
            st.warning("Identity and preserved data will not be deleted.")
            confirmed = st.checkbox("I confirm this account action", key="account_action_confirm")
            if st.button("Apply account action", disabled=not confirmed, key="account_action_apply"):
                if action_name == "lifecycle":
                    outcome = lifecycle_action(selected.account_id, desired_status, confirmed=True)
                elif action_name == "bind":
                    outcome = bind_action(selected.account_id, profile_key, confirmed=True)
                elif action_name == "auth-check":
                    outcome = auth_check_action(selected.account_id, confirmed=True)
                elif action_name == "auth-confirm":
                    outcome = auth_confirm_action(selected.account_id, confirmed=True)
                else:
                    outcome = sync_action(selected.account_id, confirmed=True)
                (st.success if outcome.ok else st.error)(outcome.message)

    st.caption(
        "Private labels come from the local account registry and remain local. "
        "Removing a profile does not remove or retire an account. The lifecycle "
        "action retires capture capability, never its "
        "identity or preserved data."
    )
