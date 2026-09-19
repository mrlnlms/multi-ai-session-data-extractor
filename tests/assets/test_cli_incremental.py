from __future__ import annotations

import json
import os

import pandas as pd

from src.assets.cli_incremental import CLIAssetCaptureSession, CLIAssetObservation
from src.assets.models import AssetScope
from src.assets.projection import project_assets
from src.assets.vault import AssetVault
from src.schema.models import Asset, AssetLink, make_asset_link_id


def _observation(data_root, payload: bytes = b"inline image") -> CLIAssetObservation:
    asset = Asset(
        asset_id="asset-1",
        source="claude_code",
        account_id=None,
        asset_kind="attachment",
        asset_origin="user",
        file_name="1_0.png",
        mime_type="image/png",
        size_bytes=len(payload),
        asset_path="raw/Claude Code/_images/session-1/1_0.png",
        is_model_generated=False,
        is_preserved_missing=False,
        is_binary_available=True,
        created_at=pd.Timestamp("2026-09-16T12:00:00"),
        metadata_json=json.dumps({"content_sha256": "fixture"}, sort_keys=True),
    )
    link = AssetLink(
        asset_link_id=make_asset_link_id(
            "claude_code", None, asset.asset_id, "message", "message-1", "input", 0, 1
        ),
        source="claude_code",
        account_id=None,
        asset_id=asset.asset_id,
        object_type="message",
        object_id="message-1",
        conversation_id="session-1",
        message_id="message-1",
        project_id=None,
        role="input",
        ordinal=0,
        content_block_index=1,
        metadata_json=None,
    )
    return CLIAssetObservation(
        asset=asset,
        link=link,
        payload=payload,
        representation_kind="user_attachment",
    )


def _session(vault, data_root) -> CLIAssetCaptureSession:
    return CLIAssetCaptureSession(
        vault,
        source="claude_code",
        account_id=None,
        evidence_path=data_root / "raw" / "Claude Code",
        data_root=data_root,
    )


def test_cli_capture_commits_before_materializing_compatible_hardlink(tmp_path):
    data_root = tmp_path / "data"
    vault = AssetVault(data_root / "assets", runtime_root=tmp_path / "runtime")
    session = _session(vault, data_root)

    session.observe(_observation(data_root))
    session.finish()

    scope = AssetScope("claude_code")
    state = vault.load_state(scope)
    projected = project_assets(state, data_root)
    assert len(projected.assets) == len(projected.links) == 1
    assert projected.links[0].content_block_index == 1
    assert projected.message_paths == {
        "message-1": (projected.assets[0].asset_path,)
    }
    compatible = data_root / "raw/Claude Code/_images/session-1/1_0.png"
    blob = data_root / projected.assets[0].asset_path
    assert compatible.read_bytes() == b"inline image"
    assert os.stat(compatible).st_ino == os.stat(blob).st_ino


def test_cli_capture_retry_is_log_idempotent_and_rebuilds_projection(tmp_path):
    data_root = tmp_path / "data"
    vault = AssetVault(data_root / "assets", runtime_root=tmp_path / "runtime")
    scope = AssetScope("claude_code")
    first = _session(vault, data_root)
    first.observe(_observation(data_root))
    first.finish()
    log_before = vault.records_path(scope).read_bytes()

    compatible = data_root / "raw/Claude Code/_images/session-1/1_0.png"
    compatible.unlink()
    retry = _session(vault, data_root)
    retry.observe(_observation(data_root))
    retry.finish()

    assert vault.records_path(scope).read_bytes() == log_before
    assert compatible.read_bytes() == b"inline image"
    assert vault.verify(scope).blob_count == 1


def test_empty_cli_capture_is_explicit_and_idempotent(tmp_path):
    data_root = tmp_path / "data"
    vault = AssetVault(data_root / "assets", runtime_root=tmp_path / "runtime")

    for _ in range(2):
        CLIAssetCaptureSession(
            vault,
            source="gemini_cli",
            account_id=None,
            evidence_path=data_root / "raw" / "Gemini CLI",
            data_root=data_root,
        ).finish()

    state = vault.load_state(AssetScope("gemini_cli"))
    assert len(state.committed_captures) == 1
    assert state.by_type["delivery"] == ()
    assert state.by_type["appearance"] == ()
    assert state.by_type["blob"] == ()
    assert state.by_type["observation"] == ()
