import hashlib
from pathlib import Path

from src.operations.asset_coverage_audit import RepresentationEvidence
from src.operations.audit_asset_retention import apply_retention, audit_retention


def _evidence(path: str) -> RepresentationEvidence:
    return RepresentationEvidence(
        source="ChatGPT",
        account_scope="default",
        representation_kind="preserved_binary",
        evidence_path=path,
        native_id=None,
        binary_path=path,
        conversation_id=None,
        message_id=None,
        project_id=None,
        observed_role=None,
    )


def _write_blob(data: Path, payload: bytes) -> None:
    digest = hashlib.sha256(payload).hexdigest()
    path = data / "assets" / "blobs" / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)


def test_audit_reports_only_byte_proven_candidates(tmp_path: Path):
    covered = tmp_path / "raw" / "ChatGPT" / "assets" / "covered.png"
    missing = tmp_path / "merged" / "ChatGPT" / "assets" / "missing.png"
    covered.parent.mkdir(parents=True)
    missing.parent.mkdir(parents=True)
    covered.write_bytes(b"covered")
    missing.write_bytes(b"missing")
    _write_blob(tmp_path, b"covered")

    report = audit_retention(
        tmp_path,
        [_evidence("raw/ChatGPT/assets/covered.png"),
         _evidence("merged/ChatGPT/assets/missing.png")],
    )

    assert report["mode"] == "read_only"
    assert report["candidate_file_count"] == 1
    assert report["candidate_logical_bytes"] == len(b"covered")
    assert report["candidates"][0]["path"] == "raw/ChatGPT/assets/covered.png"
    assert report["candidates"][0]["sha256"] == hashlib.sha256(b"covered").hexdigest()
    assert report["blocked_file_count"] == 1
    assert report["blocked"] == [{
        "path": "merged/ChatGPT/assets/missing.png",
        "reason": "vault_blob_missing",
    }]


def test_audit_deduplicates_repeated_evidence_for_same_path(tmp_path: Path):
    path = tmp_path / "raw" / "ChatGPT" / "assets" / "same.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"same")
    _write_blob(tmp_path, b"same")
    evidence = _evidence("raw/ChatGPT/assets/same.bin")

    report = audit_retention(tmp_path, [evidence, evidence])

    assert report["candidate_file_count"] == 1


def test_apply_removes_only_freshly_revalidated_candidate(tmp_path: Path):
    path = tmp_path / "raw" / "ChatGPT" / "assets" / "covered.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"covered")
    _write_blob(tmp_path, b"covered")
    report = audit_retention(tmp_path, [_evidence("raw/ChatGPT/assets/covered.png")])

    result = apply_retention(tmp_path, report)

    assert result["mode"] == "apply"
    assert result["removed_file_count"] == 1
    assert result["blocked_file_count"] == 0
    assert not path.exists()


def test_apply_preserves_candidate_changed_after_audit(tmp_path: Path):
    path = tmp_path / "merged" / "ChatGPT" / "assets" / "changed.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"covered")
    _write_blob(tmp_path, b"covered")
    report = audit_retention(tmp_path, [_evidence("merged/ChatGPT/assets/changed.png")])
    path.write_bytes(b"new bytes")

    result = apply_retention(tmp_path, report)

    assert result["removed_file_count"] == 0
    assert result["blocked"] == [{
        "path": "merged/ChatGPT/assets/changed.png",
        "reason": "candidate_changed",
    }]
    assert path.read_bytes() == b"new bytes"
