import json
import pandas as pd

from src.platforms.grok.parser import GrokParser


ACCOUNT_ID = "810f3e91-ae10-5cb1-931a-53b80630af16"


def test_assets_use_canonical_contract_and_only_publish_existing_paths(tmp_path):
    merged = tmp_path / "data/merged/Grok"
    assets_dir = merged / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "upload.pdf").write_bytes(b"pdf")
    parser = GrokParser(account_id=ACCOUNT_ID, merged_root=merged)
    parser.assets = [
        {
            "assetId": "upload", "name": "note.pdf", "mimeType": "application/pdf",
            "sizeBytes": 3, "fileSource": "SELF_UPLOAD_FILE_SOURCE",
            "key": "secret/storage/key", "createTime": "2026-01-01T00:00:00Z",
        },
        {
            "assetId": "generated", "name": "image.png", "mimeType": "image/png",
            "isModelGenerated": True, "_preserved_missing": True,
            "previewImageKey": "secret/preview/key",
        },
    ]

    frame = parser.assets_df()
    upload = frame.set_index("asset_id").loc["upload"]
    generated = frame.set_index("asset_id").loc["generated"]
    assert upload["asset_kind"] == "attachment"
    assert upload["asset_origin"] == "user"
    assert upload["asset_path"] == "merged/Grok/assets/upload.pdf"
    assert bool(upload["is_binary_available"])
    assert generated["asset_kind"] == "generated"
    assert generated["asset_origin"] == "assistant"
    assert pd.isna(generated["asset_path"])
    assert not bool(generated["is_binary_available"])
    assert bool(generated["is_preserved_missing"])
    serialized = frame.to_json(date_format="iso")
    assert "secret/storage/key" not in serialized
    assert "secret/preview/key" not in serialized
    assert json.loads(upload["metadata_json"])["file_source"] == "SELF_UPLOAD_FILE_SOURCE"


def test_assets_are_deterministic(tmp_path):
    merged = tmp_path / "data/merged/Grok"
    merged.mkdir(parents=True)
    parser = GrokParser(account_id=ACCOUNT_ID, merged_root=merged)
    parser.assets = [{"assetId": "a", "fileSource": "UNKNOWN"}]
    assert parser.assets_df().to_json(date_format="iso") == parser.assets_df().to_json(date_format="iso")


def test_global_catalog_emits_empty_exact_schema_asset_links(tmp_path):
    parser = GrokParser(account_id=ACCOUNT_ID, merged_root=tmp_path)
    frame = parser.asset_links_df()
    assert frame.empty
    assert "asset_link_id" in frame.columns
