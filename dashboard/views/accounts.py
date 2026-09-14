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
        "Read-only local inventory. Evidence is reported independently; "
        "a browser profile does not prove that authentication is valid."
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

    st.info(
        "Authentication is not tested by this view. “Unknown (not checked)” means "
        "that a local profile exists; it is not a login-health verdict."
    )

    rows = _account_rows(states)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No account definitions are available.")

    st.caption(
        "Private labels come from the local account registry and remain local. "
        "Accounts stay visible while raw, merged, or historical evidence exists."
    )
