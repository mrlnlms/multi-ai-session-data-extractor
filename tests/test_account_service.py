from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.account_catalog import AccountCatalog, LifecycleStatus, legacy_account_id
from src.account_service import create_account, set_account_metadata, set_lifecycle

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
ACCOUNT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _created():
    return create_account(
        AccountCatalog(), platform="Qwen", display_name="Work", email="me@example.test",
        now=NOW, account_id_factory=lambda: ACCOUNT_ID,
    )


def test_create_edit_and_retire_are_immutable():
    created = _created()
    record = created.after.records[-1]
    assert record.account_id == str(ACCOUNT_ID)
    assert record.display_name == "Work"
    edited = set_account_metadata(
        created.after, created.account_id, display_name="Study", email=None, now=LATER,
    )
    assert edited.after.records[-1].display_name == "Study"
    assert created.after.records[-1].display_name == "Work"
    retired = set_lifecycle(
        edited.after, created.account_id, LifecycleStatus.HISTORICAL,
        now=LATER + timedelta(hours=1),
    )
    assert retired.after.records[-1].created_at == NOW


@pytest.mark.parametrize("value", [" padded ", 3])
def test_create_rejects_invalid_presentation_text(value):
    with pytest.raises(ValueError):
        create_account(AccountCatalog(), platform="Qwen", display_name=value, now=NOW)


def test_create_rejects_duplicate_uuid_and_unsupported_platform():
    created = _created()
    with pytest.raises(ValueError, match="account_id"):
        create_account(
            created.after, platform="Qwen", now=LATER,
            account_id_factory=lambda: ACCOUNT_ID,
        )
    with pytest.raises(ValueError, match="Unsupported"):
        create_account(AccountCatalog(), platform="Unknown", now=NOW)


def test_mutations_reject_missing_noop_and_backward_time():
    created = _created()
    with pytest.raises(ValueError, match="Unknown"):
        set_lifecycle(
            created.after, legacy_account_id("Qwen", "other"),
            LifecycleStatus.DISABLED, now=LATER,
        )
    with pytest.raises(ValueError, match="no-op"):
        set_lifecycle(created.after, created.account_id, LifecycleStatus.ACTIVE, now=LATER)
    with pytest.raises(ValueError, match="no-op"):
        set_account_metadata(
            created.after, created.account_id, display_name="Work",
            email="me@example.test", now=LATER,
        )
    with pytest.raises(ValueError, match="backward"):
        set_lifecycle(
            created.after, created.account_id, LifecycleStatus.DISABLED,
            now=NOW - timedelta(seconds=1),
        )


def test_no_physical_delete_api_exists():
    import src.account_service as service
    assert not hasattr(service, "delete_account")
