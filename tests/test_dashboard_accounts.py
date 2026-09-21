from pathlib import Path

from dashboard.views.accounts import _account_rows, _actionable_accounts
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
    authentication_method: str | None = None,
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
        authentication_method=authentication_method,
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

    assert [(row["Platform"], row["Account"]) for row in rows] == [
        ("Gemini", f"Gemini · {legacy_account_id('Gemini', '1')}"),
        ("Gemini", f"Gemini · {legacy_account_id('Gemini', '2')}"),
        ("ChatGPT", f"ChatGPT · {legacy_account_id('ChatGPT', 'default')}"),
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
        "Account": "owner@example.test",
        "Account ID": legacy_account_id("Gemini", "1"),
        "Lifecycle": "Active",
        "Registry": "Present",
        "Profile": "Present",
        "Raw": "Present",
        "Merged": "—",
        "Historical": "—",
        "Authentication": "Unknown (not checked)",
        "Archive": "Data with local profile",
    }


def test_account_rows_show_authentication_evidence_method():
    account = _account("ChatGPT", "default", profile=True, authentication="valid", authentication_method="operator")
    row = _account_rows([PlatformState("ChatGPT", None, None, accounts=(account,))])[0]
    assert row["Authentication"] == "Valid — operator"


def test_account_rows_keep_data_only_account_visible_as_preserved():
    account = _account("Gemini", "retired", raw=True, merged=True)

    row = _account_rows([PlatformState("Gemini", None, None, accounts=(account,))])[0]

    assert row["Account"].startswith("Gemini · ")
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


def test_account_rows_emit_one_row_per_canonical_uuid():
    account_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    account = AccountState(
        platform="ChatGPT",
        key=account_id,
        label="Primary",
        evidence=AccountEvidence(
            profile_path=Path("profile"),
            raw_path=Path("raw"),
            merged_path=Path("merged"),
        ),
        authentication="valid",
        account_id=account_id,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )

    rows = _account_rows([PlatformState("ChatGPT", None, None, accounts=(account,))])

    assert len(rows) == 1
    assert rows[0]["Account ID"] == account_id
    assert rows[0]["Lifecycle"] == "Active"
    assert rows[0]["Profile"] == "Present"
    assert rows[0]["Raw"] == "Present"
    assert rows[0]["Merged"] == "Present"


def test_unclassified_evidence_is_visible_but_not_an_action_target():
    unclassified = AccountState(
        platform="ChatGPT",
        key="unbound",
        label=None,
        evidence=AccountEvidence(profile_path=Path("profile-unbound")),
        authentication="unknown",
        account_id=None,
        lifecycle_status=None,
    )
    catalogued = _account(
        "ChatGPT",
        "catalogued",
        lifecycle=LifecycleStatus.ACTIVE,
    )
    state = PlatformState("ChatGPT", None, None, accounts=(catalogued, unclassified))

    rows = _account_rows([state])

    assert len(rows) == 2
    assert rows[1]["Account"] == "ChatGPT · unbound"
    assert rows[1]["Account ID"] == "—"
    assert rows[1]["Lifecycle"] == "Unclassified"
    assert _actionable_accounts([state]) == [catalogued]
