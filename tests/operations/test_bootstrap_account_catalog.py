import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.account_catalog import LifecycleStatus, load_account_catalog
from src.accounts import AccountEvidence, AccountState
from src.application.platforms import PlatformState
from src.operations.bootstrap_account_catalog import build_catalog, main, serialize_catalog


CAPTURED_AT = datetime(2026, 9, 13, tzinfo=timezone.utc)


def _account(platform, key, *, label=None, profile=None, raw=None, historical=None):
    return AccountState(
        platform=platform,
        key=key,
        label=label,
        evidence=AccountEvidence(
            profile_path=Path(profile) if profile else None,
            raw_path=Path(raw) if raw else None,
            historical_path=Path(historical) if historical else None,
        ),
        authentication="unknown" if profile else "not_configured",
    )


def _states(*accounts):
    grouped = {}
    for account in accounts:
        grouped.setdefault(account.platform, []).append(account)
    return [
        PlatformState(platform, None, None, accounts=tuple(grouped[platform]))
        for platform in reversed(tuple(grouped))
    ]


def test_build_catalog_classifies_fallback_and_historical_archive():
    catalog = build_catalog(
        _states(
            _account("NotebookLM", "1"),
            _account("NotebookLM", "archive:former-work", historical="snapshot"),
        ),
        captured_at=CAPTURED_AT,
    )

    assert [record.platform for record in catalog.records] == ["NotebookLM", "NotebookLM"]
    assert all(record.account_id for record in catalog.records)
    assert [record.lifecycle_status for record in catalog.records] == [
        LifecycleStatus.ACTIVE,
        LifecycleStatus.HISTORICAL,
    ]


def test_build_catalog_requires_classification_for_nonfallback_evidence():
    with pytest.raises(ValueError, match="Qwen:retired"):
        build_catalog(
            _states(_account("Qwen", "default"), _account("Qwen", "retired", raw="raw")),
            captured_at=CAPTURED_AT,
        )


def test_explicit_classification_resolves_ambiguous_account():
    catalog = build_catalog(
        _states(_account("Qwen", "default"), _account("Qwen", "retired", raw="raw")),
        captured_at=CAPTURED_AT,
        classifications={"Qwen:retired": LifecycleStatus.DISABLED},
    )
    assert catalog.records[-1].lifecycle_status is LifecycleStatus.DISABLED


def test_serialization_is_reproducible_ordered_and_private_data_free():
    states = _states(
        _account("Qwen", "default", label="owner@example.test", profile="/secret/profile"),
        _account("ChatGPT", "default"),
    )
    first = serialize_catalog(build_catalog(states, captured_at=CAPTURED_AT))
    second = serialize_catalog(build_catalog(states, captured_at=CAPTURED_AT))

    assert first == second
    payload = json.loads(first)
    assert [record["platform"] for record in payload["accounts"]] == ["ChatGPT", "Qwen"]
    assert "owner@example.test" in first
    assert all("technical_key" not in record for record in payload["accounts"])
    assert "/secret/profile" not in first


def test_main_previews_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "src.operations.bootstrap_account_catalog.discover_platforms",
        lambda: _states(_account("Qwen", "default")),
    )
    destination = tmp_path / "catalog.json"

    assert main(["--captured-at", "2026-09-13T00:00:00Z"]) == 0
    assert not destination.exists()
    assert json.loads(capsys.readouterr().out)["accounts"][0]["platform"] == "Qwen"


def test_main_writes_atomically_and_accepts_identical_existing_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.operations.bootstrap_account_catalog.discover_platforms",
        lambda: _states(_account("Qwen", "default")),
    )
    destination = tmp_path / "nested" / "catalog.json"
    args = ["--captured-at", "2026-09-13T00:00:00Z", "--write", str(destination)]

    assert main(args) == 0
    first = destination.read_bytes()
    assert main(args) == 0
    assert destination.read_bytes() == first
    assert not list(destination.parent.glob(".*.tmp"))


def test_main_refuses_semantically_different_existing_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.operations.bootstrap_account_catalog.discover_platforms",
        lambda: _states(_account("Qwen", "default")),
    )
    destination = tmp_path / "catalog.json"
    destination.write_text(json.dumps({"version": 1, "accounts": []}))

    with pytest.raises(ValueError, match="Refusing to overwrite"):
        main(["--captured-at", "2026-09-13T00:00:00Z", "--write", str(destination)])
    assert load_account_catalog(destination).records == ()


def test_main_classify_argument_and_timezone_validation(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.operations.bootstrap_account_catalog.discover_platforms",
        lambda: _states(_account("Qwen", "retired", raw="raw")),
    )
    assert main([
        "--classify", "Qwen:retired=historical",
        "--captured-at", "2026-09-13T00:00:00Z",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["accounts"][0]["lifecycle_status"] == "historical"

    with pytest.raises(ValueError, match="timezone-aware"):
        main(["--captured-at", "2026-09-13T00:00:00"])
