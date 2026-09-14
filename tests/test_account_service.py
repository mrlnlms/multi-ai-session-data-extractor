from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.account_catalog import AccountCatalog, LifecycleStatus, legacy_account_id
from src.account_service import create_account, set_lifecycle


NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
ACCOUNT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def test_create_and_retire_are_immutable():
    catalog = AccountCatalog()
    created = create_account(
        catalog, platform="Qwen", technical_key="work", now=NOW,
        account_id_factory=lambda: ACCOUNT_ID,
    )
    record = created.after.records[-1]
    assert record.account_id == str(ACCOUNT_ID)
    assert record.lifecycle_status is LifecycleStatus.ACTIVE
    assert catalog.records == ()

    retired = set_lifecycle(created.after, created.account_id, LifecycleStatus.HISTORICAL, now=LATER)
    assert retired.after.records[-1].created_at == NOW
    assert retired.after.records[-1].updated_at == LATER


@pytest.mark.parametrize("key", ["", " work", "../work", "a/b", "a\\b", "archive:old"])
def test_create_rejects_unsafe_keys(key):
    with pytest.raises(ValueError):
        create_account(AccountCatalog(), platform="Qwen", technical_key=key, now=NOW)


def test_create_rejects_duplicates_and_unsupported_platform():
    created = create_account(AccountCatalog(), platform="Qwen", technical_key="work", now=NOW,
                             account_id_factory=lambda: ACCOUNT_ID)
    with pytest.raises(ValueError, match="identity"):
        create_account(created.after, platform="Qwen", technical_key="work", now=LATER)
    with pytest.raises(ValueError, match="account_id"):
        create_account(created.after, platform="Qwen", technical_key="other", now=LATER,
                       account_id_factory=lambda: ACCOUNT_ID)
    with pytest.raises(ValueError, match="Unsupported"):
        create_account(AccountCatalog(), platform="Unknown", technical_key="work", now=NOW)


def test_lifecycle_rejects_missing_noop_and_backward_time():
    created = create_account(AccountCatalog(), platform="Qwen", technical_key="work", now=NOW,
                             account_id_factory=lambda: ACCOUNT_ID)
    with pytest.raises(ValueError, match="Unknown"):
        set_lifecycle(created.after, str(legacy_account_id("Qwen", "other")), LifecycleStatus.DISABLED, now=LATER)
    with pytest.raises(ValueError, match="no-op"):
        set_lifecycle(created.after, created.account_id, LifecycleStatus.ACTIVE, now=LATER)
    with pytest.raises(ValueError, match="backward"):
        set_lifecycle(created.after, created.account_id, LifecycleStatus.DISABLED,
                      now=NOW - timedelta(seconds=1))


def test_no_physical_delete_api_exists():
    import src.account_service as service
    assert not hasattr(service, "delete_account")
