from __future__ import annotations

import hashlib

from src.assets.models import AssetScope, CaptureBatch, RecordEnvelope
from src.assets.vault import AssetVault


def _batch(scope: AssetScope, capture_id: str) -> CaptureBatch:
    payload = capture_id.encode()
    digest = hashlib.sha256(payload).hexdigest()
    records = tuple(
        RecordEnvelope(kind, 1, capture_id, True, body)
        for kind, body in (
            ("capture", {"sequence": capture_id}),
            ("delivery", {"delivery_id": f"delivery-{capture_id}", "sha256": digest}),
            ("blob", {"sha256": digest, "size_bytes": len(payload)}),
        )
    )
    return CaptureBatch(scope, capture_id, records, {digest: payload})


def test_rebuild_state_is_byte_for_byte_deterministic(tmp_path):
    scope = AssetScope("claude_ai", None)
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    vault.commit(_batch(scope, "capture-1"))
    vault.commit(_batch(scope, "capture-2"))
    snapshot = vault.state_path(scope)
    expected = snapshot.read_bytes()

    snapshot.unlink()
    rebuilt = vault.rebuild_state(scope)

    assert rebuilt.committed_captures == ("capture-1", "capture-2")
    assert snapshot.read_bytes() == expected


def test_load_state_rebuilds_absent_or_stale_snapshot(tmp_path):
    scope = AssetScope("claude_ai", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    vault.commit(_batch(scope, "capture-1"))
    snapshot = vault.state_path(scope)
    snapshot.write_text('{"schema_version": 1}', encoding="utf-8")

    state = vault.load_state(scope)

    assert state.committed_captures == ("capture-1",)
    assert b'"log_sha256"' in snapshot.read_bytes()


def test_identical_committed_retry_is_noop(tmp_path):
    scope = AssetScope("claude_ai", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    batch = _batch(scope, "capture-1")
    vault.commit(batch)
    log = vault.records_path(scope)
    state = vault.state_path(scope)
    before = (log.read_bytes(), state.read_bytes())

    retried = vault.commit(batch)

    assert retried.committed_captures == ("capture-1",)
    assert (log.read_bytes(), state.read_bytes()) == before
