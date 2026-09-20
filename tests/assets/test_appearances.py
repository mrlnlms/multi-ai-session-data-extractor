from __future__ import annotations

from pathlib import Path

from src.assets.appearances import (
    commit_web_asset_appearances,
    commit_web_parser_appearances,
)
from src.assets.contracts import MessagePathEvidence
from src.assets.incremental import AssetObservation, commit_web_asset_capture
from src.assets.models import AssetScope
from src.assets.projection import project_assets
from src.assets.vault import AssetVault
from src.schema.models import Asset, AssetLink, Message, make_asset_link_id

ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"


def _link(account_id: str) -> AssetLink:
    link_id = make_asset_link_id(
        "chatgpt", account_id, "asset-1", "message", "message-1", "input", 0, 2
    )
    return AssetLink(
        asset_link_id=link_id,
        source="chatgpt",
        account_id=account_id,
        asset_id="asset-1",
        object_type="message",
        object_id="message-1",
        conversation_id="conversation-1",
        message_id="message-1",
        project_id=None,
        role="input",
        ordinal=0,
        content_block_index=2,
        metadata_json=None,
    )


def test_semantic_enrichment_links_existing_delivery_and_is_idempotent(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    account_id = ACCOUNT_ID
    commit_web_asset_capture(
        vault,
        source="chatgpt",
        account_id=account_id,
        observations=(AssetObservation(
            "asset-1", "asset-1", "user_attachment", payload=b"image"
        ),),
        complete_discovery=True,
        evidence_path=tmp_path / "raw",
    )
    link = _link(account_id)
    paths = (MessagePathEvidence(
        "asset-1", "conversation-1", "message-1", 0
    ),)

    capture_id = commit_web_asset_appearances(
        vault,
        source="chatgpt",
        account_id=account_id,
        links=(link,),
        message_paths=paths,
        evidence_path=tmp_path / "merged.json",
    )
    before = vault.records_path(AssetScope("chatgpt", account_id)).read_bytes()
    assert commit_web_asset_appearances(
        vault,
        source="chatgpt",
        account_id=account_id,
        links=(link,),
        message_paths=paths,
        evidence_path=tmp_path / "merged.json",
    ) == capture_id
    assert vault.records_path(AssetScope("chatgpt", account_id)).read_bytes() == before

    projection = project_assets(
        vault.load_state(AssetScope("chatgpt", account_id)), tmp_path
    )
    assert projection.links == (link,)
    assert projection.message_paths["message-1"] == (projection.assets[0].asset_path,)


def test_semantic_enrichment_rejects_relationship_without_delivery(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    link = _link(ACCOUNT_ID)

    try:
        commit_web_asset_appearances(
            vault,
            source="chatgpt",
            account_id=ACCOUNT_ID,
            links=(link,),
            message_paths=(),
            evidence_path=Path("merged.json"),
        )
    except ValueError as exc:
        assert "no captured delivery" in str(exc)
    else:
        raise AssertionError("unknown delivery was accepted")


def test_latest_authoritative_snapshot_hides_stale_appearance_without_deleting_it(
    tmp_path,
):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    commit_web_asset_capture(
        vault,
        source="chatgpt",
        account_id=ACCOUNT_ID,
        observations=(AssetObservation(
            "asset-1", "asset-1", "user_attachment", payload=b"image"
        ),),
        complete_discovery=True,
        evidence_path=tmp_path / "raw",
    )
    stale = _link(ACCOUNT_ID)
    commit_web_asset_appearances(
        vault, source="chatgpt", account_id=ACCOUNT_ID, links=(stale,),
        message_paths=(), evidence_path=tmp_path / "first.json",
    )
    commit_web_asset_appearances(
        vault, source="chatgpt", account_id=ACCOUNT_ID, links=(),
        message_paths=(), evidence_path=tmp_path / "second.json",
    )

    state = vault.load_state(AssetScope("chatgpt", ACCOUNT_ID))
    assert len(state.by_type["appearance"]) == 1
    assert project_assets(state, tmp_path).links == ()


def test_parser_enrichment_partitions_multi_account_assets(tmp_path):
    vault = AssetVault(tmp_path / "assets", runtime_root=tmp_path / "runtime")
    accounts = (ACCOUNT_ID, "22222222-2222-4222-8222-222222222222")
    assets = []
    links = []
    messages = []
    for index, account_id in enumerate(accounts, 1):
        asset_id = f"asset-{index}"
        message_id = f"message-{index}"
        path = f"raw/Gemini/account-{index}/{asset_id}.png"
        commit_web_asset_capture(
            vault,
            source="gemini",
            account_id=account_id,
            observations=(AssetObservation(
                asset_id, asset_id, "user_attachment", payload=f"image-{index}".encode()
            ),),
            complete_discovery=True,
            evidence_path=tmp_path / f"account-{index}",
        )
        assets.append(Asset(
            asset_id=asset_id, source="gemini", account_id=account_id,
            asset_kind="attachment", asset_origin="user", file_name=f"{asset_id}.png",
            mime_type="image/png", size_bytes=7, asset_path=path,
            is_model_generated=False, is_preserved_missing=False,
            is_binary_available=True, created_at=None, metadata_json=None,
        ))
        link_id = make_asset_link_id(
            "gemini", account_id, asset_id, "message", message_id, "input", 0, 0
        )
        links.append(AssetLink(
            asset_link_id=link_id, source="gemini", account_id=account_id,
            asset_id=asset_id, object_type="message", object_id=message_id,
            conversation_id=f"conversation-{index}", message_id=message_id,
            project_id=None, role="input", ordinal=0, content_block_index=0,
            metadata_json=None,
        ))
        messages.append(Message(
            message_id=message_id, conversation_id=f"conversation-{index}",
            source="gemini", account_id=account_id, sequence=0, role="user",
            content="upload", model=None, created_at=None, asset_paths=[path],
        ))

    capture_ids = commit_web_parser_appearances(
        vault, source="gemini", assets=assets, links=links, messages=messages,
        evidence_path=tmp_path / "merged",
    )

    assert len(capture_ids) == 2
    for index, account_id in enumerate(accounts, 1):
        projection = project_assets(
            vault.load_state(AssetScope("gemini", account_id)), tmp_path
        )
        assert [asset.asset_id for asset in projection.assets] == [f"asset-{index}"]
        assert [link.message_id for link in projection.links] == [f"message-{index}"]
