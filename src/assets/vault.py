"""Crash-recoverable append-only asset vault with global content-addressed blobs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import fcntl

from .models import (
    AssetScope,
    AssetState,
    CaptureBatch,
    RecordEnvelope,
    VerificationReport,
    validate_digest,
)
from .state import (
    canonical_json,
    capture_fingerprint,
    encode_envelope,
    encode_state,
    fold_committed_records,
    state_from_dict,
)


class AssetVaultError(RuntimeError):
    """Base class for durable vault failures."""


class AssetVaultLockedError(AssetVaultError):
    """Raised when another process already owns a scope's writer lock."""


class IntegrityError(AssetVaultError):
    """Raised when a content-addressed blob is absent or does not match its record."""


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_capture(path: Path, encoded: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                raise OSError("incomplete capture append")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class AssetVault:
    """Store committed record batches per scope and immutable blobs globally."""

    def __init__(self, root: Path, *, runtime_root: Path | None = None) -> None:
        self.root = Path(root)
        self.runtime_root = (
            Path(runtime_root)
            if runtime_root is not None
            else self.root.parent / ".runtime" / "asset-vault"
        )

    def records_path(self, scope: AssetScope) -> Path:
        return self._scope_path(scope) / "records.jsonl"

    def state_path(self, scope: AssetScope) -> Path:
        return self._scope_path(scope) / "state.json"

    def blob_path(self, sha256: str) -> Path:
        digest = validate_digest(sha256)
        return self.root / "blobs" / "sha256" / digest[:2] / digest

    def _scope_path(self, scope: AssetScope) -> Path:
        if not isinstance(scope, AssetScope):
            raise TypeError("scope must be an AssetScope")
        return self.root / "scopes" / scope.source / scope.account_key

    @contextmanager
    def lock(self, scope: AssetScope) -> Iterator[None]:
        lock_path = self.runtime_root / scope.source / f"{scope.account_key}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AssetVaultLockedError(
                    f"asset vault scope is locked: {scope.source}/{scope.account_key}"
                ) from exc
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def commit(self, batch: CaptureBatch) -> AssetState:
        if not isinstance(batch, CaptureBatch):
            raise TypeError("batch must be a CaptureBatch")
        with self.lock(batch.scope):
            self._ensure_schema()
            log_path = self.records_path(batch.scope)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._recover_for_append(log_path)
            captures, committed_log, commits = self._read_committed(log_path)
            fingerprint = capture_fingerprint(batch.records)
            previous = commits.get(batch.capture_id)
            if previous is not None:
                if previous != (len(batch.records), fingerprint):
                    raise ValueError(
                        f"capture_id {batch.capture_id!r} was already committed with different records"
                    )
                for digest, payload in batch.blobs.items():
                    self._write_blob(digest, payload)
                self._verify_batch_blob_records(batch)
                return self._load_or_rebuild_state(batch.scope, captures, committed_log)

            for digest, payload in batch.blobs.items():
                self._write_blob(digest, payload)
            self._verify_batch_blob_records(batch)

            marker = RecordEnvelope(
                record_type="capture_commit",
                record_version=1,
                capture_id=batch.capture_id,
                complete=True,
                payload={"record_count": len(batch.records), "records_sha256": fingerprint},
            )
            encoded = b"".join(encode_envelope(record) for record in (*batch.records, marker))
            _append_capture(log_path, encoded)
            _fsync_directory(log_path.parent)
            captures, committed_log, _ = self._read_committed(log_path)
            return self._write_state(batch.scope, captures, committed_log)

    def read_blob(self, sha256: str) -> bytes:
        digest = validate_digest(sha256)
        path = self.blob_path(digest)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise IntegrityError(f"missing blob: {digest}") from exc
        if hashlib.sha256(payload).hexdigest() != digest:
            raise IntegrityError(f"blob checksum mismatch: {digest}")
        return payload

    def load_state(self, scope: AssetScope) -> AssetState:
        captures, committed_log, _ = self._read_committed(self.records_path(scope))
        current = self._read_current_state(scope, captures, committed_log)
        if current is not None:
            return current
        with self.lock(scope):
            captures, committed_log, _ = self._read_committed(self.records_path(scope))
            return self._load_or_rebuild_state(scope, captures, committed_log)

    def rebuild_state(self, scope: AssetScope) -> AssetState:
        with self.lock(scope):
            captures, committed_log, _ = self._read_committed(self.records_path(scope))
            return self._write_state(scope, captures, committed_log)

    def verify(self, scope: AssetScope) -> VerificationReport:
        state = self.load_state(scope)
        verified: set[str] = set()
        for record in state.records:
            if record.record_type != "blob":
                continue
            digest = record.payload.get("sha256")
            size = record.payload.get("size_bytes")
            if not isinstance(digest, str):
                raise IntegrityError("blob record has no valid sha256")
            payload = self.read_blob(digest)
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise IntegrityError(f"blob record has invalid size: {digest}")
            if len(payload) != size:
                raise IntegrityError(f"blob size mismatch: {digest}")
            verified.add(digest)
        return VerificationReport(
            scope=scope,
            capture_count=len(state.committed_captures),
            record_count=len(state.records),
            blob_count=len(verified),
        )

    def _ensure_schema(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "schema.json"
        expected = canonical_json(
            {
                "envelope_version": 1,
                "record_types": [
                    "capture", "delivery", "appearance", "blob", "observation",
                    "capture_commit",
                ],
            }
        ) + b"\n"
        if path.exists():
            if path.read_bytes() != expected:
                raise ValueError("asset vault schema.json is incompatible")
            return
        self._publish_exclusive(path, expected)

    def _write_blob(self, digest: str, payload: bytes) -> None:
        path = self.blob_path(digest)
        if path.exists():
            existing = self.read_blob(digest)
            if len(existing) != len(payload):
                raise IntegrityError(f"blob size mismatch: {digest}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".incoming-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise IntegrityError(f"temporary blob checksum mismatch: {digest}")
            try:
                os.link(temporary, path)
            except FileExistsError:
                self.read_blob(digest)
            _fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _verify_batch_blob_records(self, batch: CaptureBatch) -> None:
        for record in batch.records:
            if record.record_type != "blob":
                continue
            digest = record.payload.get("sha256")
            size = record.payload.get("size_bytes")
            if not isinstance(digest, str):
                raise IntegrityError("blob record has no valid sha256")
            payload = self.read_blob(digest)
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise IntegrityError(f"blob record has invalid size: {digest}")
            if len(payload) != size:
                raise IntegrityError(f"blob size mismatch: {digest}")

    def _publish_exclusive(self, path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise ValueError(f"existing {path.name} has incompatible content")
            _fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _recover_for_append(self, path: Path) -> None:
        if not path.exists():
            return
        content = path.read_bytes()
        newline_end = len(content) if content.endswith(b"\n") else content.rfind(b"\n") + 1
        prefix = content[:newline_end]
        self._parse_lines(prefix)
        _, committed, _ = self._read_committed_bytes(prefix)
        if committed == content:
            return
        descriptor = os.open(path, os.O_WRONLY)
        try:
            os.ftruncate(descriptor, len(committed))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(path.parent)

    def _read_committed(
        self, path: Path
    ) -> tuple[
        tuple[tuple[RecordEnvelope, ...], ...],
        bytes,
        dict[str, tuple[int, str]],
    ]:
        if not path.exists():
            return (), b"", {}
        content = path.read_bytes()
        complete = content if content.endswith(b"\n") else content[: content.rfind(b"\n") + 1]
        return self._read_committed_bytes(complete)

    def _read_committed_bytes(
        self, content: bytes
    ) -> tuple[
        tuple[tuple[RecordEnvelope, ...], ...],
        bytes,
        dict[str, tuple[int, str]],
    ]:
        rows = self._parse_lines(content)
        captures: list[tuple[RecordEnvelope, ...]] = []
        commits: dict[str, tuple[int, str]] = {}
        pending: list[RecordEnvelope] = []
        committed_end = 0
        byte_offset = 0
        for row, encoded in rows:
            byte_offset += len(encoded)
            if row.record_type != "capture_commit":
                if pending and pending[0].capture_id != row.capture_id:
                    raise ValueError("capture records are interleaved or missing a commit marker")
                pending.append(row)
                continue
            if not pending or any(record.capture_id != row.capture_id for record in pending):
                raise ValueError("capture_commit does not follow its capture records")
            count = row.payload.get("record_count")
            fingerprint = row.payload.get("records_sha256")
            expected = capture_fingerprint(tuple(pending))
            if count != len(pending) or fingerprint != expected:
                raise ValueError(f"capture_commit validation failed for {row.capture_id!r}")
            if row.capture_id in commits:
                raise ValueError(f"duplicate capture_commit for {row.capture_id!r}")
            commits[row.capture_id] = (len(pending), expected)
            captures.append(tuple(pending))
            pending = []
            committed_end = byte_offset
        return tuple(captures), content[:committed_end], commits

    @staticmethod
    def _parse_lines(content: bytes) -> list[tuple[RecordEnvelope, bytes]]:
        rows: list[tuple[RecordEnvelope, bytes]] = []
        for line_number, encoded in enumerate(content.splitlines(keepends=True), 1):
            if not encoded.endswith(b"\n"):
                continue
            try:
                value = json.loads(encoded)
                row = RecordEnvelope.from_dict(value)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid JSON record at line {line_number}") from exc
            rows.append((row, encoded))
        return rows

    def _load_or_rebuild_state(
        self,
        scope: AssetScope,
        captures: tuple[tuple[RecordEnvelope, ...], ...],
        committed_log: bytes,
    ) -> AssetState:
        current = self._read_current_state(scope, captures, committed_log)
        if current is not None:
            return current
        return self._write_state(scope, captures, committed_log)

    def _read_current_state(
        self,
        scope: AssetScope,
        captures: tuple[tuple[RecordEnvelope, ...], ...],
        committed_log: bytes,
    ) -> AssetState | None:
        expected = fold_committed_records(scope, captures, committed_log)
        path = self.state_path(scope)
        if path.exists():
            try:
                value = json.loads(path.read_bytes())
                current = state_from_dict(value)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                current = None
            if current == expected:
                return current
        return None

    def _write_state(
        self,
        scope: AssetScope,
        captures: tuple[tuple[RecordEnvelope, ...], ...],
        committed_log: bytes,
    ) -> AssetState:
        state = fold_committed_records(scope, captures, committed_log)
        path = self.state_path(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encode_state(state))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return state
