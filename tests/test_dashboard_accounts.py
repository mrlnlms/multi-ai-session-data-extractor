from pathlib import Path

from dashboard.views.accounts import _account_rows
from src.account_catalog import LifecycleStatus, legacy_account_id
from src.accounts import AccountEvidence, AccountState
from src.application.platforms import PlatformState


def _account(
    platform: str,
    key: str,
    *,
    label: str | None = None,
    registry: bool = False,
    profile: bool = False,
    raw: bool = False,
    merged: bool = False,
    historical: bool = False,
    authentication: str = "not_configured",
    lifecycle: LifecycleStatus | None = None,
) -> AccountState:
    return AccountState(
        platform=platform,
        key=key,
        label=label,
        evidence=AccountEvidence(
            registry_present=registry,
            profile_path=Path(f"profile-{key}") if profile else None,
            raw_path=Path(f"raw-{key}") if raw else None,
            merged_path=Path(f"merged-{key}") if merged else None,
            historical_path=Path(f"historical-{key}") if historical else None,
        ),
        authentication=authentication,
        account_id=legacy_account_id(platform, key),
        lifecycle_status=lifecycle,
    )


def test_account_rows_preserve_platform_and_service_order():
    states = [
        PlatformState(
            "Gemini",
            None,
            None,
            accounts=(
                _account("Gemini", "1"),
                _account("Gemini", "2"),
            ),
        ),
        PlatformState(
            "ChatGPT",
            None,
            None,
            accounts=(_account("ChatGPT", "default"),),
        ),
    ]

    rows = _account_rows(states)

    assert [(row["Platform"], row["Technical account"]) for row in rows] == [
        ("Gemini", "1"),
        ("Gemini", "2"),
        ("ChatGPT", "default"),
    ]


def test_account_rows_expose_independent_evidence_without_claiming_login():
    account = _account(
        "Gemini",
        "1",
        label="owner@example.test",
        registry=True,
        profile=True,
        raw=True,
        authentication="unknown",
        lifecycle=LifecycleStatus.ACTIVE,
    )

    row = _account_rows([PlatformState("Gemini", None, None, accounts=(account,))])[0]

    assert row == {
        "Platform": "Gemini",
        "Technical account": "1",
        "Account ID": legacy_account_id("Gemini", "1"),
        "Lifecycle": "Active",
        "Private label": "owner@example.test",
        "Registry": "Present",
        "Profile": "Present",
        "Raw": "Present",
        "Merged": "—",
        "Historical": "—",
        "Authentication": "Unknown (not checked)",
        "Archive": "Data with local profile",
    }


def test_account_rows_keep_data_only_account_visible_as_preserved():
    account = _account("Gemini", "retired", raw=True, merged=True)

    row = _account_rows([PlatformState("Gemini", None, None, accounts=(account,))])[0]

    assert row["Private label"] == "—"
    assert row["Authentication"] == "Not configured"
    assert row["Archive"] == "Preserved data without profile"
    assert row["Lifecycle"] == "Unclassified"


def test_account_rows_describe_fallback_without_local_evidence():
    account = _account("ChatGPT", "default")

    row = _account_rows([PlatformState("ChatGPT", None, None, accounts=(account,))])[0]

    assert row["Archive"] == "No local data"


def test_account_rows_show_historical_archive_without_login_claim():
    account = _account(
        "NotebookLM",
        "archive:more-design-2026-03-30",
        historical=True,
        lifecycle=LifecycleStatus.HISTORICAL,
    )

    row = _account_rows([PlatformState("NotebookLM", None, None, accounts=(account,))])[0]

    assert row["Historical"] == "Present"
    assert row["Raw"] == "—"
    assert row["Merged"] == "—"
    assert row["Authentication"] == "Not configured"
    assert row["Archive"] == "Historical archive"
    assert row["Lifecycle"] == "Historical"


def test_active_account_without_profile_keeps_independent_statuses():
    account = _account(
        "Qwen",
        "default",
        raw=True,
        lifecycle=LifecycleStatus.ACTIVE,
    )

    row = _account_rows([PlatformState("Qwen", None, None, accounts=(account,))])[0]

    assert row["Account ID"] == account.account_id
    assert row["Lifecycle"] == "Active"
    assert row["Authentication"] == "Not configured"
    assert row["Archive"] == "Preserved data without profile"
