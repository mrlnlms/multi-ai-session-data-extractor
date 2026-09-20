from __future__ import annotations

import hashlib
import uuid

import pytest

from src.assets.models import AssetScope, CaptureBatch, RecordEnvelope
from src.assets.projection import project_assets
from src.assets.vault import AssetVault, IntegrityError


ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"


def _record(record_type: str, capture_id: str, **payload: object) -> RecordEnvelope:
    return RecordEnvelope(record_type, 1, capture_id, True, payload)


def _commit(
    tmp_path,
    *,
    source: str = "gemini",
    capture_id: str = "capture-1",
    deliveries: tuple[dict[str, object], ...],
    appearances: tuple[dict[str, object], ...] = (),
    observations: tuple[dict[str, object], ...] = (),
    payloads: tuple[bytes, ...] = (),
):
    data_root = tmp_path / "data"
    vault = AssetVault(data_root / "assets", runtime_root=tmp_path / "runtime")
    scope = AssetScope(source, ACCOUNT_ID)
    blobs = {hashlib.sha256(payload).hexdigest(): payload for payload in payloads}
    records = [_record("capture", capture_id, captured_at="2026-09-16T12:00:00Z")]
    records.extend(_record("delivery", capture_id, **row) for row in deliveries)
    records.extend(_record("appearance", capture_id, **row) for row in appearances)
    records.extend(
        _record("blob", capture_id, sha256=digest, size_bytes=len(payload))
        for digest, payload in blobs.items()
    )
    records.extend(_record("observation", capture_id, **row) for row in observations)
    state = vault.commit(CaptureBatch(scope, capture_id, tuple(records), blobs))
    return data_root, vault, state


def _delivery(
    delivery_id: str,
    *,
    payload: bytes | None = None,
    representation_kind: str = "delivery",
    file_name: str | None = "asset.bin",
) -> dict[str, object]:
    return {
        "delivery_id": delivery_id,
        "object_id": f"object-{delivery_id}",
        "representation_kind": representation_kind,
        "file_name": file_name,
        "mime_type": "application/octet-stream" if payload is not None else None,
        "size_bytes": len(payload) if payload is not None else None,
        "sha256": hashlib.sha256(payload).hexdigest() if payload is not None else None,
        "availability": "available" if payload is not None else "reference_only",
    }


def _message_appearance(
    appearance_id: str,
    delivery_id: str,
    message_id: str,
    *,
    ordinal: int,
    content_block_index: int | None = None,
) -> dict[str, object]:
    return {
        "appearance_id": appearance_id,
        "delivery_id": delivery_id,
        "object_type": "message",
        "object_id": message_id,
        "conversation_id": "conversation-1",
        "message_id": message_id,
        "project_id": None,
        "role": "input",
        "ordinal": ordinal,
        "content_block_index": content_block_index,
        "position_confidence": "exact",
    }


def test_multiple_appearances_share_one_asset_and_keep_ordered_message_paths(tmp_path):
    payload = b"shared image"
    data_root, _, state = _commit(
        tmp_path,
        deliveries=(_delivery("native-upload", payload=payload, representation_kind="user_attachment"),),
        appearances=(
            _message_appearance("appearance-1", "native-upload", "message-1", ordinal=0),
            _message_appearance("appearance-2", "native-upload", "message-2", ordinal=1),
        ),
        observations=({"observation_id": "observation-1", "delivery_id": "native-upload", "status": "available"},),
        payloads=(payload,),
    )

    projection = project_assets(state, data_root)

    assert len(projection.assets) == 1
    assert len(projection.links) == 2
    assert projection.assets[0].asset_kind == "attachment"
    assert projection.assets[0].asset_origin == "user"
    assert projection.assets[0].is_model_generated is False
    assert projection.message_paths == {
        "message-1": (projection.assets[0].asset_path,),
        "message-2": (projection.assets[0].asset_path,),
    }
    assert all(str(uuid.UUID(link.asset_link_id)) == link.asset_link_id for link in projection.links)


def test_reference_without_bytes_has_no_path_and_unpositioned_use_fabricates_no_link(tmp_path):
    data_root, _, state = _commit(
        tmp_path,
        source="deepseek",
        deliveries=(_delivery("metadata-only", payload=None, file_name="report.pdf"),),
        appearances=({
            "appearance_id": "appearance-1",
            "delivery_id": "metadata-only",
            "object_type": None,
            "object_id": None,
            "conversation_id": None,
            "message_id": None,
            "project_id": None,
            "role": "unknown",
            "ordinal": None,
            "content_block_index": None,
            "position_confidence": "unproven",
        },),
        observations=({"observation_id": "observation-1", "delivery_id": "metadata-only", "status": "reference_only"},),
    )

    projection = project_assets(state, data_root)

    assert projection.assets[0].asset_path is None
    assert projection.assets[0].is_binary_available is False
    assert projection.links == ()
    assert projection.message_paths == {}


def test_notebooklm_representations_map_explicitly_without_using_extensions(tmp_path):
    payloads = (b"pdf", b"pptx", b'{"text":"answer"}')
    deliveries = (
        _delivery("slides-pdf", payload=payloads[0], file_name="slides.unknown"),
        _delivery("slides-pptx", payload=payloads[1], file_name="slides.pdf"),
        _delivery(
            "answer-envelope",
            payload=payloads[2],
            representation_kind="text_artifact_envelope",
            file_name="answer.bin",
        ),
    )
    appearances = tuple({
        "appearance_id": f"appearance-{index}",
        "delivery_id": delivery["delivery_id"],
        "object_type": "output",
        "object_id": "slide-output",
        "conversation_id": None,
        "message_id": None,
        "project_id": None,
        "role": "output",
        "ordinal": index,
        "content_block_index": None,
        "position_confidence": "exact",
    } for index, delivery in enumerate(deliveries))
    data_root, _, state = _commit(
        tmp_path,
        source="notebooklm",
        deliveries=deliveries,
        appearances=appearances,
        observations=tuple({
            "observation_id": f"observation-{index}",
            "delivery_id": delivery["delivery_id"],
            "status": "available",
        } for index, delivery in enumerate(deliveries)),
        payloads=payloads,
    )

    projection = project_assets(state, data_root)
    by_id = {asset.asset_id: asset for asset in projection.assets}

    assert by_id["slides-pdf"].asset_kind == "other"
    assert by_id["slides-pptx"].asset_kind == "other"
    assert by_id["answer-envelope"].asset_kind == "output"
    assert by_id["answer-envelope"].asset_origin == "assistant"
    assert by_id["answer-envelope"].is_model_generated is True
    assert len(projection.links) == 3


def test_cli_position_preserves_exact_content_block_index(tmp_path):
    payload = b"inline image"
    data_root, _, state = _commit(
        tmp_path,
        source="claude_code",
        deliveries=(_delivery("session-message-block", payload=payload, representation_kind="user_attachment"),),
        appearances=(_message_appearance(
            "appearance-1", "session-message-block", "message-1", ordinal=0, content_block_index=0
        ),),
        observations=({"observation_id": "observation-1", "delivery_id": "session-message-block", "status": "available"},),
        payloads=(payload,),
    )

    projection = project_assets(state, data_root)

    assert projection.links[0].content_block_index == 0
    assert projection.links[0].ordinal == 0


def test_projection_order_restores_public_link_order_across_capture_batches(tmp_path):
    payload = b"ordered"
    appearances = (
        {**_message_appearance("appearance-later", "asset-1", "message-1", ordinal=1),
         "projection_order": 8},
        {**_message_appearance("appearance-first", "asset-1", "message-2", ordinal=0),
         "projection_order": 2},
    )
    data_root, _, state = _commit(
        tmp_path,
        deliveries=(_delivery("asset-1", payload=payload),),
        appearances=appearances,
        payloads=(payload,),
    )

    projection = project_assets(state, data_root)

    assert [link.message_id for link in projection.links] == [
        "message-2", "message-1"
    ]


def test_duplicate_appearance_accepts_legacy_projection_order_difference(tmp_path):
    payload = b"ordered"
    appearance = _message_appearance(
        "appearance-1", "asset-1", "message-1", ordinal=0
    )
    data_root, vault, _ = _commit(
        tmp_path,
        deliveries=(_delivery("asset-1", payload=payload),),
        appearances=({**appearance, "projection_order": 7},),
        payloads=(payload,),
    )

    state = vault.commit(CaptureBatch(
        AssetScope("gemini", ACCOUNT_ID),
        "capture-2",
        (
            _record("capture", "capture-2", captured_at="2026-09-20T12:00:00Z"),
            _record("appearance", "capture-2", **appearance),
        ),
        {},
    ))

    projection = project_assets(state, data_root)

    assert len(projection.links) == 1
    assert projection.links[0].message_id == "message-1"


def test_duplicate_appearance_still_rejects_semantic_conflict(tmp_path):
    payload = b"ordered"
    appearance = _message_appearance(
        "appearance-1", "asset-1", "message-1", ordinal=0
    )
    data_root, vault, _ = _commit(
        tmp_path,
        deliveries=(_delivery("asset-1", payload=payload),),
        appearances=({**appearance, "projection_order": 7},),
        payloads=(payload,),
    )
    conflicting = {**appearance, "message_id": "message-2"}
    state = vault.commit(CaptureBatch(
        AssetScope("gemini", ACCOUNT_ID),
        "capture-2",
        (
            _record("capture", "capture-2", captured_at="2026-09-20T12:00:00Z"),
            _record("appearance", "capture-2", **conflicting),
        ),
        {},
    ))

    with pytest.raises(ValueError, match="conflicting appearance record"):
        project_assets(state, data_root)


def test_complete_and_partial_discovery_statuses_project_without_losing_preserved_bytes(tmp_path):
    payloads = (b"still preserved", b"currently visible",)
    deliveries = (
        _delivery("missing-upstream", payload=payloads[0]),
        _delivery("visible", payload=payloads[1]),
        _delivery("reference", payload=None),
    )
    data_root, _, state = _commit(
        tmp_path,
        deliveries=deliveries,
        observations=(
            {"observation_id": "complete-missing", "delivery_id": "missing-upstream", "status": "preserved_missing"},
            {"observation_id": "partial-visible", "delivery_id": "visible", "status": "available"},
            {"observation_id": "partial-reference", "delivery_id": "reference", "status": "reference_only"},
        ),
        payloads=payloads,
    )

    projection = project_assets(state, data_root)
    by_id = {asset.asset_id: asset for asset in projection.assets}

    assert by_id["missing-upstream"].is_preserved_missing is True
    assert by_id["missing-upstream"].is_binary_available is True
    assert by_id["missing-upstream"].asset_path is not None
    assert by_id["visible"].is_preserved_missing is False
    assert by_id["reference"].is_preserved_missing is False
    assert by_id["reference"].asset_path is None


@pytest.mark.parametrize("damage", ["corrupt", "missing"])
def test_projection_rejects_corrupt_or_missing_available_blob(tmp_path, damage):
    payload = b"verified payload"
    data_root, vault, state = _commit(
        tmp_path,
        deliveries=(_delivery("delivery-1", payload=payload),),
        observations=({"observation_id": "observation-1", "delivery_id": "delivery-1", "status": "available"},),
        payloads=(payload,),
    )
    digest = hashlib.sha256(payload).hexdigest()
    blob = vault.blob_path(digest)
    if damage == "corrupt":
        blob.write_bytes(b"x" * len(payload))
    else:
        blob.unlink()

    with pytest.raises(IntegrityError, match=damage if damage == "missing" else "checksum"):
        project_assets(state, data_root)


def test_unknown_representation_kind_is_rejected_instead_of_guessed_from_extension(tmp_path):
    payload = b"looks like a PDF but classification is absent"
    data_root, _, state = _commit(
        tmp_path,
        deliveries=(_delivery("delivery-1", payload=payload, representation_kind="mystery", file_name="report.pdf"),),
        payloads=(payload,),
    )

    with pytest.raises(ValueError, match="unsupported representation_kind"):
        project_assets(state, data_root)
