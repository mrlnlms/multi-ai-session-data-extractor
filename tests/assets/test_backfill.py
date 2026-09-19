from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.assets.contracts import SourceInputs
from src.schema.models import (
    Asset,
    AssetLink,
    assets_to_df,
    asset_links_to_df,
    make_asset_link_id,
    messages_to_df,
    Message,
)
from src.workflows.asset_projection import project_source_assets


ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"


def _write_inputs(tmp_path: Path) -> SourceInputs:
    input_root = tmp_path / "input"
    processed = input_root / "processed" / "Gemini"
    binary = input_root / "raw" / "Gemini" / "asset.bin"
    processed.mkdir(parents=True)
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"verified asset")

    available = Asset(
        asset_id="asset-available",
        source="gemini",
        account_id=ACCOUNT_ID,
        asset_kind="attachment",
        asset_origin="user",
        file_name="misleading.txt",
        mime_type="application/octet-stream",
        size_bytes=len(b"verified asset"),
        asset_path="raw/Gemini/asset.bin",
        is_model_generated=False,
        is_preserved_missing=False,
        is_binary_available=True,
        created_at=pd.Timestamp("2026-09-16 12:00:00"),
        metadata_json=json.dumps({"native_id": "asset-available"}),
    )
    reference = Asset(
        asset_id="asset-reference",
        source="gemini",
        account_id=ACCOUNT_ID,
        asset_kind="other",
        asset_origin="unknown",
        file_name=None,
        mime_type=None,
        size_bytes=None,
        asset_path=None,
        is_model_generated=None,
        is_preserved_missing=False,
        is_binary_available=False,
        created_at=None,
        metadata_json=None,
    )
    link_id = make_asset_link_id(
        "gemini", ACCOUNT_ID, available.asset_id, "message", "message-1", "input", 0, 2
    )
    link = AssetLink(
        asset_link_id=link_id,
        source="gemini",
        account_id=ACCOUNT_ID,
        asset_id=available.asset_id,
        object_type="message",
        object_id="message-1",
        conversation_id="conversation-1",
        message_id="message-1",
        project_id=None,
        role="input",
        ordinal=0,
        content_block_index=2,
        metadata_json=json.dumps({"native_position": 2}),
    )
    message = Message(
        message_id="message-1",
        conversation_id="conversation-1",
        source="gemini",
        sequence=0,
        role="user",
        content="attachment",
        model=None,
        created_at=pd.Timestamp("2026-09-16 12:00:00"),
        branch_id="conversation-1_main",
        asset_paths=["raw/Gemini/asset.bin"],
        account_id=ACCOUNT_ID,
    )
    assets_to_df([available, reference]).to_parquet(processed / "gemini_assets.parquet")
    asset_links_to_df([link]).to_parquet(processed / "gemini_asset_links.parquet")
    messages_to_df([message]).to_parquet(processed / "gemini_messages.parquet")
    evidence = input_root / "merged" / "Gemini"
    evidence.mkdir(parents=True)
    return SourceInputs(
        data_root=input_root,
        assets_path=processed / "gemini_assets.parquet",
        asset_links_path=processed / "gemini_asset_links.parquet",
        messages_path=processed / "gemini_messages.parquet",
        evidence_paths=(evidence,),
        max_batch_bytes=1024,
    )


def test_backfill_is_idempotent_and_projects_verified_legacy_rows(tmp_path):
    inputs = _write_inputs(tmp_path)
    output_root = tmp_path / "output"
    vault_root = output_root / "assets"

    first = project_source_assets("gemini", inputs, vault_root, output_root)
    records = next(vault_root.glob("scopes/gemini/*/records.jsonl"))
    first_log = records.read_bytes()
    second = project_source_assets("gemini", inputs, vault_root, output_root)

    assert records.read_bytes() == first_log
    assert first == second
    assert first.asset_count == 2
    assert first.link_count == 1
    assert first.available_count == 1
    assert first.message_path_count == 1
    assert first.commit_count == 1
    assert first.assets[0].asset_path.startswith("assets/blobs/sha256/")
    assert first.assets[0].asset_kind == "attachment"
    assert first.assets[0].created_at == pd.Timestamp("2026-09-16 12:00:00")
    assert first.assets[0].metadata_json == json.dumps({"native_id": "asset-available"})
    assert first.links[0].asset_link_id == link_id_for(first.links[0])
    assert first.links[0].metadata_json == json.dumps({"native_position": 2})
    assert first.message_paths == {"message-1": (first.assets[0].asset_path,)}
    assert (output_root / "asset-projections" / "gemini" / "assets.parquet").exists()


def link_id_for(link: AssetLink) -> str:
    return make_asset_link_id(
        link.source,
        link.account_id,
        link.asset_id,
        link.object_type,
        link.object_id,
        link.role,
        link.ordinal,
        link.content_block_index,
    )


def test_all_source_adapters_are_importable_and_gemini_cli_is_explicitly_empty():
    from src.workflows.asset_projection import load_asset_adapter, source_inputs_from_data

    expected = {
        "chatgpt": "chatgpt",
        "claude_ai": "manifest_tree_web",
        "gemini": "manifest_tree_web",
        "notebooklm": "notebooklm_historical",
        "qwen": "manifest_tree_web",
        "deepseek": "manifest_tree_web",
        "perplexity": "manifest_tree_web",
        "grok": "manifest_tree_web",
        "kimi": "manifest_tree_web",
        "claude_code": "cli_inline",
        "codex": "cli_inline",
        "gemini_cli": "gemini_cli_empty",
        "antigravity_cli": "cli_inline",
    }
    assert {source: load_asset_adapter(source).family for source in expected} == expected
    notebook = source_inputs_from_data(Path("data"), "notebooklm")
    assert notebook.assets_path.name == "notebooklm_assets.parquet"
    assert Path("data/external/notebooklm-snapshots") in notebook.evidence_paths
    chatgpt = source_inputs_from_data(Path("data"), "chatgpt")
    assert Path("data/external/manual-saves") in chatgpt.evidence_paths


def test_gemini_cli_empty_projection_commits_once_and_retries_without_growth(tmp_path):
    processed = tmp_path / "input" / "processed" / "Gemini CLI"
    processed.mkdir(parents=True)
    assets_to_df([]).to_parquet(processed / "gemini_cli_assets.parquet")
    asset_links_to_df([]).to_parquet(processed / "gemini_cli_asset_links.parquet")
    messages_to_df([]).to_parquet(processed / "gemini_cli_messages.parquet")
    inputs = SourceInputs(
        data_root=tmp_path / "input",
        assets_path=processed / "gemini_cli_assets.parquet",
        asset_links_path=processed / "gemini_cli_asset_links.parquet",
        messages_path=processed / "gemini_cli_messages.parquet",
    )
    output = tmp_path / "output"

    first = project_source_assets("gemini_cli", inputs, output / "assets", output)
    second = project_source_assets("gemini_cli", inputs, output / "assets", output)

    assert first == second
    assert first.asset_count == first.link_count == first.available_count == 0
    assert first.commit_count == 1
