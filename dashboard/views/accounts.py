"""Read-only account inventory backed by the application state."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.accounts import AccountState
from src.application.platforms import PlatformState


def _present(value: bool) -> str:
    return "Present" if value else "—"


def _authentication_label(value: str) -> str:
    labels = {
        "unknown": "Unknown (not checked)",
        "not_configured": "Not configured",
    }
    return labels.get(value, value.replace("_", " ").title())


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
                    "Authentication": _authentication_label(account.authentication),
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
        "Authentication is not tested by this view. “Unknown (not checked)” means "
        "that a local profile exists; it is not a login-health verdict. "
        "Unclassified means evidence exists without a catalog lifecycle decision."
    )

    rows = _account_rows(states)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No account definitions are available.")

    st.caption(
        "Private labels come from the local account registry and remain local. "
        "Removing a profile does not remove or retire an account. A future product "
        "action to delete an account will retire capture capability, never its "
        "identity or preserved data."
    )
