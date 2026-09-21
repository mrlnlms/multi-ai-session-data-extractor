from __future__ import annotations

import hashlib
import json

import pytest

from src.assets.incremental import (
    AssetObservation,
    WebAssetCaptureSession,
    commit_web_asset_capture,
)
from src.assets.models import AssetScope
from src.assets.vault import AssetVault


def _available(delivery_id: str = "asset-1") -> AssetObservation:
    return AssetObservation(
        delivery_id=delivery_id,
        object_id=delivery_id,
        representation_kind="delivery",
        payload=b"durable bytes",
        file_name="asset.bin",
        mime_type="application/octet-stream",
        upstream_locator=f"https://example.test/{delivery_id}",
    )


def test_none_keeps_legacy_mode_side_effect_free(tmp_path):
    assert commit_web_asset_capture(
        None,
        source="gemini",
        account_id="account-one",
        observations=(_available(),),
        complete_discovery=True,
        evidence_path=tmp_path / "raw",
    ) is None
    assert list(tmp_path.iterdir()) == []


def test_partial_discovery_does_not_mark_unseen_delivery_missing(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    kwargs = {
        "asset_vault": vault,
        "source": "gemini",
        "account_id": "account-one",
        "evidence_path": tmp_path / "raw",
    }
    commit_web_asset_capture(
        **kwargs,
        observations=(_available("asset-1"), _available("asset-2")),
        complete_discovery=True,
    )
    commit_web_asset_capture(
        **kwargs,
        observations=(_available("asset-1"),),
        complete_discovery=False,
    )

    state = vault.load_state(AssetScope("gemini", "account-one"))
    missing = [
        row
        for row in state.by_type["observation"]
        if row.payload.get("status") == "preserved_missing"
    ]
    assert missing == []


def test_complete_discovery_marks_only_unseen_known_delivery_missing(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    kwargs = {
        "asset_vault": vault,
        "source": "gemini",
        "account_id": "account-one",
        "evidence_path": tmp_path / "raw",
    }
    commit_web_asset_capture(
        **kwargs,
        observations=(_available("asset-1"), _available("asset-2")),
        complete_discovery=True,
    )
    commit_web_asset_capture(
        **kwargs,
        observations=(_available("asset-1"),),
        complete_discovery=True,
    )

    state = vault.load_state(AssetScope("gemini", "account-one"))
    assert [
        row.payload["delivery_id"]
        for row in state.by_type["observation"]
        if row.payload.get("status") == "preserved_missing"
    ] == ["asset-2"]


def test_http_failure_preserves_reference_without_downgrading_available(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    kwargs = {
        "asset_vault": vault,
        "source": "gemini",
        "account_id": "account-one",
        "evidence_path": tmp_path / "raw",
        "complete_discovery": True,
    }
    commit_web_asset_capture(**kwargs, observations=(_available(),))
    failed = AssetObservation(
        delivery_id="asset-1",
        object_id="asset-1",
        representation_kind="delivery",
        upstream_locator="https://example.test/rotated",
        failure_reason="HTTP 403",
    )
    commit_web_asset_capture(**kwargs, observations=(failed,))

    state = vault.load_state(AssetScope("gemini", "account-one"))
    latest = state.by_type["observation"][-1].payload
    assert latest["observed_status"] == "reference_only"
    assert latest["status"] == "available"
    assert latest["failure_reason"] == "HTTP 403"
    assert len(state.by_type["delivery"]) == 1
    vault.verify(state.scope)


def test_reference_promoted_to_bytes_is_not_downgraded_by_later_failure(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    kwargs = {
        "asset_vault": vault,
        "source": "deepseek",
        "account_id": "account-one",
        "evidence_path": tmp_path / "raw",
        "complete_discovery": True,
    }
    reference = AssetObservation(
        delivery_id="file-1",
        object_id="file-1",
        representation_kind="user_attachment",
        failure_reason="HTTP 404",
    )
    available = AssetObservation(
        delivery_id="file-1",
        object_id="file-1",
        representation_kind="user_attachment",
        payload=b"recovered bytes",
    )

    commit_web_asset_capture(**kwargs, observations=(reference,))
    commit_web_asset_capture(**kwargs, observations=(available,))
    commit_web_asset_capture(
        **kwargs,
        observations=(
            AssetObservation(
                delivery_id="file-1",
                object_id="file-1",
                representation_kind="user_attachment",
                failure_reason="HTTP 503",
            ),
        ),
    )

    state = vault.load_state(AssetScope("deepseek", "account-one"))
    assert state.by_type["observation"][-1].payload["status"] == "available"
    assert len(state.by_type["delivery"]) == 1
    assert vault.verify(state.scope).blob_count == 1


def test_blob_is_durable_before_commit_marker_and_retry_is_idempotent(
    tmp_path, monkeypatch
):
    from src.assets import vault as vault_module

    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    observation = _available()
    real_append = vault_module._append_capture
    failed = False

    def fail_before_marker(path, encoded):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("between blob and capture commit")
        return real_append(path, encoded)

    monkeypatch.setattr(vault_module, "_append_capture", fail_before_marker)
    kwargs = {
        "asset_vault": vault,
        "source": "gemini",
        "account_id": "account-one",
        "observations": (observation,),
        "complete_discovery": True,
        "evidence_path": tmp_path / "raw",
    }
    with pytest.raises(OSError, match="between blob and capture commit"):
        commit_web_asset_capture(**kwargs)

    digest = hashlib.sha256(observation.payload).hexdigest()
    assert vault.blob_path(digest).read_bytes() == observation.payload
    assert vault.load_state(AssetScope("gemini", "account-one")).records == ()

    capture_id = commit_web_asset_capture(**kwargs)
    assert commit_web_asset_capture(**kwargs) == capture_id
    rows = [
        json.loads(line)
        for line in vault.records_path(AssetScope("gemini", "account-one"))
        .read_text()
        .splitlines()
    ]
    assert [row["record_type"] for row in rows].count("capture_commit") == 1


def test_capture_session_bounds_payload_batches_and_commits_discovery(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    session = WebAssetCaptureSession(
        vault,
        source="notebooklm",
        account_id="account-one",
        evidence_path=tmp_path / "raw",
        capture_method="captured_responses",
        max_batch_bytes=4,
    )

    session.observe(
        AssetObservation("asset-1", "asset-1", "assistant_output", payload=b"1234")
    )
    session.observe(
        AssetObservation("asset-2", "asset-2", "assistant_output", payload=b"5678")
    )
    session.finish(complete_discovery=True)

    state = vault.load_state(AssetScope("notebooklm", "account-one"))
    assert len(state.committed_captures) == 3
    assert len(state.by_type["delivery"]) == 2
    assert vault.verify(state.scope).blob_count == 2


def test_capture_session_retires_only_vault_backed_staging_files(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    staging = tmp_path / "raw" / "assets"
    backed = staging / "nested" / "backed.bin"
    unbacked = staging / "keep.bin"
    backed.parent.mkdir(parents=True)
    backed.write_bytes(b"vault-backed")
    unbacked.write_bytes(b"not-observed")
    session = WebAssetCaptureSession(
        vault,
        source="gemini",
        account_id="account-one",
        evidence_path=tmp_path / "raw",
        capture_method="fixture",
        staging_root=staging,
    )
    session.observe(
        AssetObservation("asset-1", "asset-1", "attachment", payload=b"vault-backed")
    )

    session.finish(complete_discovery=True)

    assert not backed.exists()
    assert not backed.parent.exists()
    assert unbacked.read_bytes() == b"not-observed"
