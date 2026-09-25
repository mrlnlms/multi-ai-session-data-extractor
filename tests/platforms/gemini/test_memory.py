"""Gemini account Instructions projection and fail-closed lifecycle tests."""

from datetime import datetime, timezone

import pytest

from src.platforms.gemini.extractor.api_client import validate_instructions_envelope
from src.platforms.gemini.extractor.orchestrator import _persist_instructions_snapshot
from src.platforms.gemini.memory_parser import parse_account_instructions


ACCOUNT_ID = "254d222d-d434-5916-980d-048269857023"


def _item(content: str = "synthetic instruction", native_id: str = "native-id") -> list:
    return [
        native_id, content, [1_725_000_000, 123], None,
        [1_725_000_100, 456], None, None, None, 1, 2, 3,
    ]


def _capture(root, hour: int, envelope: list) -> None:
    _persist_instructions_snapshot(
        root, envelope, observed_at=datetime(2026, 9, 23, hour, tzinfo=timezone.utc),
    )


def test_deleted_instruction_stays_projected_with_native_evidence(tmp_path):
    _capture(tmp_path, 17, [[_item()], "opaque-tail"])
    _capture(tmp_path, 18, [])

    result = parse_account_instructions(tmp_path, ACCOUNT_ID)

    assert len(result.memories) == len(result.versions) == 1
    memory = result.memories[0]
    version = result.versions[0]
    assert memory.memory_id == f"gemini:{ACCOUNT_ID}:instructions/native-id"
    assert memory.kind == "account_instructions"
    assert memory.is_preserved_missing is True
    assert memory.content == "synthetic instruction"
    assert memory.current_version_id == version.version_id
    assert version.created_at_basis == "first_observed"
    assert version.updated_at_basis == "last_observed"
    assert version.source_modified_at is None
    assert {item.evidence_type for item in result.temporal_evidence} == {
        "capture_observed", "native_timestamp_field_2", "native_timestamp_field_4",
    }


def test_repeated_and_edited_instruction_versions_are_stable(tmp_path):
    _capture(tmp_path, 17, [[_item()], "opaque-tail"])
    _capture(tmp_path, 18, [[_item()], "opaque-tail"])
    _capture(tmp_path, 19, [[_item("edited")], "opaque-tail"])

    result = parse_account_instructions(tmp_path, ACCOUNT_ID)

    assert len(result.memories) == 1
    assert len(result.versions) == 2
    assert result.memories[0].content == "edited"
    assert result.memories[0].is_preserved_missing is False
    assert result.memories[0].current_version_id in {
        item.version_id for item in result.versions
    }
    original = next(item for item in result.versions if item.content == "synthetic instruction")
    assert original.last_seen_at == datetime(2026, 9, 23, 18, tzinfo=timezone.utc)
    assert len(result.temporal_evidence) == 7


def test_invalid_snapshot_hash_fails_instead_of_marking_missing(tmp_path):
    observation = _persist_instructions_snapshot(
        tmp_path, [[_item()], "opaque-tail"],
        observed_at=datetime(2026, 9, 23, 17, tzinfo=timezone.utc),
    )
    (tmp_path / observation["snapshot_path"]).write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        parse_account_instructions(tmp_path, ACCOUNT_ID)


@pytest.mark.parametrize("envelope", [
    None, {}, [[], "opaque-tail"], [[_item(), _item()], "opaque-tail"],
    [[_item() for _ in range(100)], "opaque-tail"],
])
def test_malformed_or_unproven_complete_lists_are_rejected(envelope):
    with pytest.raises(ValueError):
        validate_instructions_envelope(envelope)
