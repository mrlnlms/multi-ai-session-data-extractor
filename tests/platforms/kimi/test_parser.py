import json
import pandas as pd

from src.platforms.kimi.parser import KimiParser


ACCOUNT_ID = "810f3e91-ae10-5cb1-931a-53b80630af16"


def test_assets_are_account_aware_and_omit_signed_urls(tmp_path):
    merged = tmp_path / "data/merged/Kimi/account-2"
    binary = merged / "assets/chat-1/file-1.pdf"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"pdf")
    parser = KimiParser(account_id=ACCOUNT_ID, merged_root=merged)
    parser.assets_manifest = {
        "file-1": {
            "chat_id": "chat-1", "name": "one.pdf", "mime": "application/pdf",
            "size": 3, "relpath": "assets/chat-1/file-1.pdf",
            "url": "https://cdn.example/file?X-Amz-Signature=secret",
        },
        "file-2": {
            "chat_id": "chat-1", "name": "missing.txt", "mime": "text/plain",
            "relpath": "assets/chat-1/file-2.txt",
            "url": "https://cdn.example/file?token=secret",
        },
    }

    frame = parser.assets_df().set_index("asset_id")
    assert frame.loc["file-1", "asset_path"] == "merged/Kimi/account-2/assets/chat-1/file-1.pdf"
    assert bool(frame.loc["file-1", "is_binary_available"])
    assert pd.isna(frame.loc["file-2", "asset_path"])
    assert not bool(frame.loc["file-2", "is_binary_available"])
    assert set(frame["asset_origin"]) == {"unknown"}
    assert "http" not in frame.reset_index().to_json()
    assert "secret" not in frame.reset_index().to_json()
    links = parser.asset_links_df()
    assert set(links["object_type"]) == {"conversation"}
    assert set(links["object_id"]) == {"chat-1"}
    assert set(links["role"]) == {"unknown"}
    assert links["asset_link_id"].is_unique


def test_message_only_publishes_available_asset_paths(tmp_path):
    merged = tmp_path / "data/merged/Kimi"
    available = merged / "assets/chat-1/file-1.pdf"
    available.parent.mkdir(parents=True)
    available.write_bytes(b"pdf")
    parser = KimiParser(account_id=ACCOUNT_ID, merged_root=merged)
    parser.assets_manifest = {
        "file-1": {"relpath": "assets/chat-1/file-1.pdf"},
        "file-2": {"relpath": "assets/chat-1/file-2.pdf"},
    }
    message = parser._build_message(
        "chat-1", {"files": [{"id": "file-1"}, {"id": "file-2"}]},
        {"id": "message-1", "role": "user", "blocks": []}, 1, {},
    )
    assert message.asset_paths == ["merged/Kimi/assets/chat-1/file-1.pdf"]


def test_account_aggregation_keys_do_not_change_native_asset_id(tmp_path):
    merged = tmp_path / "data/merged/Kimi/account-2"
    merged.mkdir(parents=True)
    parser = KimiParser(merged_root=tmp_path / "data/merged/Kimi")
    parser.assets_manifest = {
        f"{ACCOUNT_ID}:same": {
            "asset_id": "same", "account_id": ACCOUNT_ID,
            "chat_id": "chat-1", "_merged_root": str(merged),
        }
    }
    assert parser.assets_df().iloc[0]["asset_id"] == "same"
