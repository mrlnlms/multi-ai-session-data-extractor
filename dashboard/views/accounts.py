"""Read-only account inventory backed by the application state."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.accounts import AccountState
from src.application.platforms import PlatformState
from src.account_catalog import LifecycleStatus
from src.application.accounts import (
    account_actions, add_account_action, auth_check_action, auth_confirm_action, bind_action,
    lifecycle_action, sync_action,
)
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
                    "Technical account": account.key,
                    "Account ID": account.account_id,
                    "Lifecycle": _lifecycle_label(account),
                    "Private label": account.label or "—",
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


def render(states: list[PlatformState]) -> None:
    st.title("Accounts")
    st.caption(
        "Read-only local inventory. Lifecycle is an explicit archival decision; "
        "authentication and local evidence are reported independently."
    )
    with st.expander("Add account"):
        platform_name = st.selectbox("Platform", sorted(WEB_PLATFORMS), key="account_add_platform")
        technical_key = st.text_input("Technical profile key", key="account_add_key")
        if st.button("Preview add account", key="account_add_preview"):
            st.session_state["account_add_pending"] = (platform_name, technical_key)
        pending = st.session_state.get("account_add_pending")
        if pending:
            st.warning("Identity and preserved data will not be deleted.")
            confirmed = st.checkbox("I confirm this account catalog change", key="account_add_confirm")
            if st.button("Apply add account", disabled=not confirmed, key="account_add_apply"):
                outcome = add_account_action(platform=pending[0], technical_key=pending[1], confirmed=True)
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

    st.subheader("Account actions")
    selected = st.selectbox("Account", accounts,
        format_func=lambda item: f"{item.platform} · {item.key} · {item.account_id}",
        key="account_action_selected") if accounts else None
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
