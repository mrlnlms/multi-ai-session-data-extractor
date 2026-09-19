from __future__ import annotations

import hashlib
import json
import os
import stat

import pytest

from src.assets.models import AssetScope, CaptureBatch, RecordEnvelope
from src.assets.vault import AssetVault, AssetVaultLockedError, IntegrityError


def _envelope(record_type: str, capture_id: str, **payload: object) -> RecordEnvelope:
    return RecordEnvelope(
        record_type=record_type,
        record_version=1,
        capture_id=capture_id,
        complete=True,
        payload=payload,
    )


def _batch(
    scope: AssetScope,
    capture_id: str = "capture-1",
    payload: bytes = b"shared bytes",
    delivery_id: str = "delivery-1",
) -> CaptureBatch:
    digest = hashlib.sha256(payload).hexdigest()
    return CaptureBatch(
        scope=scope,
        capture_id=capture_id,
        records=(
            _envelope("capture", capture_id, captured_at="2026-09-16T12:00:00Z"),
            _envelope(
                "delivery",
                capture_id,
                delivery_id=delivery_id,
                sha256=digest,
                availability="available",
            ),
            _envelope("blob", capture_id, sha256=digest, size_bytes=len(payload)),
        ),
        blobs={digest: payload},
    )


def test_commit_publishes_blob_log_and_rebuildable_state(tmp_path):
    scope = AssetScope("gemini", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    batch = _batch(scope)

    state = vault.commit(batch)
    digest = next(iter(batch.blobs))

    assert state.committed_captures == ("capture-1",)
    assert [record.record_type for record in state.records] == [
        "capture", "delivery", "blob",
    ]
    assert vault.read_blob(digest) == b"shared bytes"
    assert vault.records_path(scope).read_bytes().endswith(b"\n")
    rows = [json.loads(line) for line in vault.records_path(scope).read_text().splitlines()]
    assert rows[-1]["record_type"] == "capture_commit"
    assert rows[-1]["payload"]["record_count"] == 3

    report = vault.verify(scope)
    assert report.capture_count == 1
    assert report.record_count == 3
    assert report.blob_count == 1


def test_reader_ignores_capture_without_commit(tmp_path):
    scope = AssetScope("gemini", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    path = vault.records_path(scope)
    path.parent.mkdir(parents=True)
    uncommitted = _envelope("delivery", "capture-interrupted", delivery_id="hidden")
    path.write_text(json.dumps(uncommitted.to_dict()) + "\n", encoding="utf-8")

    before = path.read_bytes()
    state = vault.load_state(scope)

    assert state.records == ()
    assert state.committed_captures == ()
    assert path.read_bytes() == before


def test_retry_recovers_partial_append_and_commits_once(tmp_path, monkeypatch):
    from src.assets import vault as vault_module

    scope = AssetScope("gemini", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    batch = _batch(scope)
    original = vault_module._append_capture
    interrupted = False

    def append_partially(path, encoded):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(descriptor, encoded[: len(encoded) // 2])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            raise OSError("simulated interruption")
        return original(path, encoded)

    monkeypatch.setattr(vault_module, "_append_capture", append_partially)
    with pytest.raises(OSError, match="simulated interruption"):
        vault.commit(batch)

    state = vault.commit(batch)
    rows = [json.loads(line) for line in vault.records_path(scope).read_text().splitlines()]
    assert state.committed_captures == ("capture-1",)
    assert [row["record_type"] for row in rows].count("capture_commit") == 1
    assert len(rows) == 4


def test_complete_invalid_json_blocks_reader_and_recovery(tmp_path):
    scope = AssetScope("gemini", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    vault.commit(_batch(scope))
    path = vault.records_path(scope)
    with path.open("ab") as stream:
        stream.write(b'{"record_type":\n')
    before = path.read_bytes()

    with pytest.raises(ValueError, match="invalid JSON record at line 5"):
        vault.commit(_batch(scope, capture_id="capture-2", delivery_id="delivery-2"))
    assert path.read_bytes() == before


def test_scope_lock_rejects_a_second_writer(tmp_path):
    scope = AssetScope("gemini", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")

    with vault.lock(scope):
        with pytest.raises(AssetVaultLockedError, match="gemini/account-one"):
            vault.commit(_batch(scope))


def test_commit_fsyncs_regular_files_and_directories(tmp_path, monkeypatch):
    from src.assets import vault as vault_module

    scope = AssetScope("gemini", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    real_fsync = os.fsync
    modes: list[int] = []

    def observed_fsync(descriptor):
        modes.append(os.fstat(descriptor).st_mode)
        return real_fsync(descriptor)

    monkeypatch.setattr(vault_module.os, "fsync", observed_fsync)
    vault.commit(_batch(scope))

    assert any(stat.S_ISREG(mode) for mode in modes)
    assert any(stat.S_ISDIR(mode) for mode in modes)


def test_integrity_detects_corrupt_and_missing_blobs(tmp_path):
    scope = AssetScope("gemini", "account-one")
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    batch = _batch(scope)
    vault.commit(batch)
    digest = next(iter(batch.blobs))
    blob_path = vault.blob_path(digest)

    blob_path.write_bytes(b"corrupt")
    with pytest.raises(IntegrityError, match="checksum mismatch"):
        vault.read_blob(digest)
    with pytest.raises(IntegrityError, match="checksum mismatch"):
        vault.verify(scope)

    blob_path.unlink()
    with pytest.raises(IntegrityError, match="missing blob"):
        vault.verify(scope)


def test_scopes_share_blob_bytes_without_sharing_identity(tmp_path):
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    one = AssetScope("gemini", "account-one")
    two = AssetScope("chatgpt", "account-two")
    vault.commit(_batch(one, delivery_id="gemini-delivery"))
    vault.commit(_batch(two, delivery_id="chatgpt-delivery"))

    assert len(list((tmp_path / "vault" / "blobs" / "sha256").glob("*/*"))) == 1
    assert vault.load_state(one).records[1].payload["delivery_id"] == "gemini-delivery"
    assert vault.load_state(two).records[1].payload["delivery_id"] == "chatgpt-delivery"
