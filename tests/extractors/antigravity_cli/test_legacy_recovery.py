import json
from pathlib import Path

import pytest

from src.extractors.antigravity_cli.legacy_recovery import (
    legacy_ids_without_transcript,
    recover_conversations,
    source_pb,
)


def _write_matching_pb(source_root: Path, raw_root: Path, conversation_id: str) -> None:
    (source_root / "conversations").mkdir(parents=True, exist_ok=True)
    (raw_root / "conversations").mkdir(parents=True, exist_ok=True)
    payload = f"opaque:{conversation_id}".encode()
    (source_root / "conversations" / f"{conversation_id}.pb").write_bytes(payload)
    (raw_root / "conversations" / f"{conversation_id}.pb").write_bytes(payload)


def test_legacy_ids_select_only_pb_without_current_transcript(tmp_path):
    raw = tmp_path / "raw"
    _write_matching_pb(tmp_path / "source", raw, "needs-recovery")
    _write_matching_pb(tmp_path / "source", raw, "already-readable")
    transcript = raw / "brain" / "already-readable" / ".system_generated" / "logs"
    transcript.mkdir(parents=True)
    (transcript / "transcript.jsonl").write_text("{}\n")

    assert legacy_ids_without_transcript(raw) == ["needs-recovery"]


def test_source_pb_requires_identical_preserved_copy(tmp_path):
    source = tmp_path / "source"
    raw = tmp_path / "raw"
    _write_matching_pb(source, raw, "legacy")
    assert source_pb("legacy", source, raw) == raw / "conversations" / "legacy.pb"

    (source / "conversations" / "legacy.pb").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="differs from local source"):
        source_pb("legacy", source, raw)


def test_recovery_writes_hashed_sidecar_and_skips_matching_rerun(tmp_path):
    source = tmp_path / "source"
    raw = tmp_path / "raw"
    _write_matching_pb(source, raw, "legacy")
    calls = []

    def fetch(conversation_id: str, ports: list[int]):
        calls.append((conversation_id, ports))
        return {"cascadeId": conversation_id, "steps": []}, 12345

    first = recover_conversations(
        ["legacy"], source_root=source, raw_root=raw, ports=[12345], fetch=fetch
    )
    second = recover_conversations(
        ["legacy"], source_root=source, raw_root=raw, ports=[12345], fetch=fetch
    )

    assert first == {"recovered": 1, "skipped": 0, "failed": 0}
    assert second == {"recovered": 0, "skipped": 1, "failed": 0}
    assert calls == [("legacy", [12345])]
    output = raw / "recovered" / "legacy.trajectory.json"
    assert json.loads(output.read_text()) == {"cascadeId": "legacy", "steps": []}
    manifest = [json.loads(line) for line in (raw / "recovered" / "recovery_manifest.jsonl").read_text().splitlines()]
    assert len(manifest) == 1
    assert manifest[0]["conversation_id"] == "legacy"
    assert manifest[0]["status"] == "recovered"

