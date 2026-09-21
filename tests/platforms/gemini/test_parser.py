"""Testes do GeminiParser v3 — schema raw posicional (batchexecute)."""

import json
import uuid
from pathlib import Path

import pytest

from src.platforms.gemini.parser import GeminiParser
from src.platforms.gemini._parser_helpers import (
    _path,
    conv_last_timestamp,
    conv_turns,
    extract_image_urls_from_turn,
    turn_assistant_text,
    turn_model_name,
    turn_thinking_blocks,
    turn_timestamp_secs,
    turn_user_text,
)


def _make_turn(user_text: str, asst_text: str, ts: int, model: str = "2.5 Flash",
               thinking: list[str] | None = None,
               images: list[str] | None = None) -> list:
    """Constroi um turn no formato raw[0][i]."""
    main_response = [
        f"rc_{hash(asst_text) & 0xffffff:x}",
        [asst_text],
        None, None, None, None, None, None,
        None, None, None, None, None, None,
        None, None, None, None, None, None,
        None,
    ]
    while len(main_response) < 38:
        main_response.append(None)
    if thinking:
        main_response[37] = [[t] for t in thinking]
    if images:
        main_response[1] = [asst_text + "\n" + " ".join(images)]

    response_data = [[main_response]] + [None] * 7
    response_data.append("BR")
    response_data.extend([True, False, None])
    response_data.extend([None] * 9)
    response_data.append(model)
    response_data.extend([None, None, 1])

    turn = [
        ["c_test", "r_test"],
        ["c_test", "r_a", "r_b"],
        [[user_text], 1, None],
        response_data,
        [ts, 0],
    ]
    return turn


def test_gemini_helpers_path():
    arr = [[1, [2, 3]], [4, 5]]
    assert _path(arr, 0, 1, 0) == 2
    assert _path(arr, 0, 1, 5, default="def") == "def"
    assert _path(arr, 99, default=None) is None
    assert _path(None, 0, default="ok") == "ok"


def test_gemini_extract_user_text():
    turn = _make_turn("Hello", "Hi!", 1700000000)
    assert turn_user_text(turn) == "Hello"


def test_gemini_extract_assistant_text():
    turn = _make_turn("Hello", "Hi there!", 1700000000)
    assert turn_assistant_text(turn) == "Hi there!"


def test_gemini_extract_model_name():
    turn = _make_turn("q", "a", 1700000000, model="3 Pro")
    assert turn_model_name(turn) == "3 Pro"


def test_gemini_extract_timestamp():
    turn = _make_turn("q", "a", 1762000000)
    assert turn_timestamp_secs(turn) == 1762000000


def test_gemini_extract_thinking_blocks():
    long_block = "Initiating analysis. " * 50
    turn = _make_turn("q", "a", 1700000000, thinking=[long_block])
    blocks = turn_thinking_blocks(turn)
    assert len(blocks) == 1
    assert long_block in blocks[0]


def test_gemini_extract_thinking_excludes_main_response():
    response = "Long response. " * 50
    turn = _make_turn("q", response, 1700000000, thinking=[response])
    blocks = turn_thinking_blocks(turn)
    assert blocks == []


def test_gemini_extract_image_urls():
    img_url = "https://lh3.googleusercontent.com/abc123=s512"
    turn = _make_turn("q", "Look at this", 1700000000, images=[img_url])
    urls = extract_image_urls_from_turn(turn)
    assert img_url in urls


def test_gemini_extract_image_urls_excludes_favicons():
    bad_url = "https://t0.gstatic.com/faviconV2?url=foo"
    good_url = "https://lh3.googleusercontent.com/img"
    turn = _make_turn("q", "x", 1700000000, images=[bad_url, good_url])
    urls = extract_image_urls_from_turn(turn)
    assert good_url in urls
    assert bad_url not in urls


def test_gemini_conv_turns_filters_non_lists():
    raw = [
        [_make_turn("q1", "a1", 1000), None, _make_turn("q2", "a2", 2000)],
        None, None, []
    ]
    turns = conv_turns(raw)
    assert len(turns) == 2


def test_gemini_conv_last_timestamp_returns_max():
    raw = [
        [_make_turn("q1", "a1", 1000), _make_turn("q2", "a2", 3000), _make_turn("q3", "a3", 2000)],
        None, None, []
    ]
    assert conv_last_timestamp(raw) == 3000


def test_gemini_parser_minimal_conv(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    acc_dir = merged / "account-1"
    (acc_dir / "conversations").mkdir(parents=True)

    raw = [
        [_make_turn("Hello", "Hi!", 1762000000, model="2.5 Flash")],
        None, None, []
    ]
    obj = {"uuid": "c_test", "raw": raw, "_last_seen_in_server": "2026-05-02"}
    (acc_dir / "conversations" / "c_test.json").write_text(json.dumps(obj))

    disc = [{"uuid": "c_test", "title": "Test conv", "created_at_secs": 1762000000}]
    (acc_dir / "discovery_ids.json").write_text(json.dumps(disc))

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    assert len(parser.conversations) == 1
    conv = parser.conversations[0]
    assert conv.conversation_id == "account-1_c_test"
    assert conv.title == "Test conv"
    assert conv.account == "1"
    assert conv.model == "2.5 Flash"

    assert len(parser.messages) == 2
    assert parser.messages[0].role == "user"
    assert parser.messages[0].content == "Hello"
    assert parser.messages[1].role == "assistant"
    assert parser.messages[1].content == "Hi!"
    assert parser.messages[1].model == "2.5 Flash"


def test_gemini_parser_namespaces_account_in_conv_id(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    for acc in [1, 2, 3]:
        d = merged / f"account-{acc}" / "conversations"
        d.mkdir(parents=True)
        raw = [[_make_turn(f"q acc {acc}", f"a acc {acc}", 1762000000)], None, None, []]
        obj = {"uuid": "c_dup", "raw": raw}
        (d / "c_dup.json").write_text(json.dumps(obj))
        (merged / f"account-{acc}" / "discovery_ids.json").write_text(
            json.dumps([{"uuid": "c_dup", "title": f"Test {acc}", "created_at_secs": 1762000000}])
        )

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    ids = {c.conversation_id for c in parser.conversations}
    assert ids == {"account-1_c_dup", "account-2_c_dup", "account-3_c_dup"}


def test_gemini_parser_uses_email_label_without_changing_ids(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    account_dir = merged / "account-1" / "conversations"
    account_dir.mkdir(parents=True)
    (account_dir / "c_test.json").write_text(json.dumps({
        "uuid": "c_test", "raw": [[_make_turn("q", "a", 1762000000)], None, None, []],
    }))

    parser = GeminiParser(
        merged_root=merged,
        account_labels={"account-1": "name@example.com"},
    )
    parser.parse(merged)

    assert parser.conversations[0].conversation_id == "account-1_c_test"
    assert parser.conversations[0].account == "name@example.com"
    assert {message.account for message in parser.messages} == {"name@example.com"}


def test_gemini_parser_preserved_missing(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    acc_dir = merged / "account-1"
    (acc_dir / "conversations").mkdir(parents=True)

    raw = [[_make_turn("q", "a", 1762000000)], None, None, []]
    obj = {
        "uuid": "c_deleted",
        "raw": raw,
        "_preserved_missing": True,
        "_last_seen_in_server": "2026-04-30",
    }
    (acc_dir / "conversations" / "c_deleted.json").write_text(json.dumps(obj))
    (acc_dir / "discovery_ids.json").write_text(
        json.dumps([{"uuid": "c_deleted", "title": "Deleted",
                     "created_at_secs": 1762000000, "_deleted_from_server": True}])
    )

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    assert len(parser.conversations) == 1
    assert parser.conversations[0].is_preserved_missing is True


def test_gemini_parser_image_generation_emits_tool_event(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    acc_dir = merged / "account-1"
    (acc_dir / "conversations").mkdir(parents=True)

    img_url = "https://lh3.googleusercontent.com/test_img"
    raw = [[_make_turn("draw cat", "here", 1762000000, model="Nano Banana", images=[img_url])],
           None, None, []]
    obj = {"uuid": "c_img", "raw": raw}
    (acc_dir / "conversations" / "c_img.json").write_text(json.dumps(obj))
    (acc_dir / "discovery_ids.json").write_text(
        json.dumps([{"uuid": "c_img", "title": "Img test", "created_at_secs": 1762000000}])
    )

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    img_events = [e for e in parser.events if e.event_type == "image_generation"]
    assert len(img_events) == 1
    assert img_events[0].tool_name == "gemini_image"


def test_gemini_parser_emits_deduplicated_assets_and_distinct_message_uses(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    raw_root = tmp_path / "raw" / "Gemini"
    account_id = str(uuid.uuid4())
    image_url = "https://lh3.googleusercontent.com/same-image=s512?token=secret"
    image_bytes = b"same preserved image"

    for account, conv_id in ((1, "c_first"), (2, "c_second")):
        conv_dir = merged / f"account-{account}" / "conversations"
        asset_dir = merged / f"account-{account}" / "assets"
        manifest_dir = raw_root / f"account-{account}"
        conv_dir.mkdir(parents=True)
        asset_dir.mkdir(parents=True)
        manifest_dir.mkdir(parents=True)
        filename = f"image-{account}.png"
        (asset_dir / filename).write_bytes(image_bytes)
        (manifest_dir / "assets_manifest.json").write_text(json.dumps({
            f"url-key-{account}": {
                "url": image_url,
                "conv_id": conv_id,
                "content_type": "image/png",
                "size": len(image_bytes),
                "filename": filename,
            },
        }))
        turn = _make_turn("draw", "done", 1762000000, images=[image_url])
        (conv_dir / f"{conv_id}.json").write_text(json.dumps({
            "uuid": conv_id, "raw": [[turn], None, None, []],
        }))

    parser = GeminiParser(
        merged_root=merged,
        account_ids={"1": account_id, "2": str(uuid.uuid4())},
    )
    parser.parse(merged)

    assert len(parser.assets) == 2  # account provenance is part of identity
    assert len(parser.asset_links) == 2
    first = parser.assets[0]
    assert first.asset_kind == "generated"
    assert first.asset_origin == "assistant"
    assert first.is_model_generated is True
    assert first.is_binary_available is True
    assert first.asset_path.startswith("merged/Gemini/account-1/assets/")
    assert "http" not in (first.metadata_json or "")
    link = parser.asset_links[0]
    assert link.object_type == "message"
    assert link.role == "output"
    assert link.message_id == "account-1_c_first_t0_asst"
    assert link.ordinal == 0


def test_gemini_parser_canonicalizes_message_path_for_duplicate_representation(
    tmp_path: Path,
):
    merged = tmp_path / "merged" / "Gemini"
    raw_root = tmp_path / "raw" / "Gemini"
    conv_dir = merged / "account-1" / "conversations"
    asset_dir = merged / "account-1" / "assets"
    manifest_dir = raw_root / "account-1"
    conv_dir.mkdir(parents=True)
    asset_dir.mkdir(parents=True)
    manifest_dir.mkdir(parents=True)
    image_bytes = b"same preserved image"
    first_url = "https://lh3.googleusercontent.com/first"
    duplicate_url = "https://lh3.googleusercontent.com/duplicate"
    (asset_dir / "first.png").write_bytes(image_bytes)
    (asset_dir / "duplicate.png").write_bytes(image_bytes)
    (manifest_dir / "assets_manifest.json").write_text(json.dumps({
        "first": {
            "url": first_url, "conv_id": "c_first", "content_type": "image/png",
            "size": len(image_bytes), "filename": "first.png",
        },
        "duplicate": {
            "url": duplicate_url, "conv_id": "c_second", "content_type": "image/png",
            "size": len(image_bytes), "filename": "duplicate.png",
        },
    }))
    for conv_id, url in (("c_first", first_url), ("c_second", duplicate_url)):
        turn = _make_turn("draw", "done", 1762000000, images=[url])
        (conv_dir / f"{conv_id}.json").write_text(json.dumps({
            "uuid": conv_id, "raw": [[turn], None, None, []],
        }))

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    assert len(parser.assets) == 1
    assert len(parser.asset_links) == 2
    expected_path = parser.assets[0].asset_path
    image_messages = [message for message in parser.messages if message.asset_paths]
    assert len(image_messages) == 2
    assert {tuple(message.asset_paths or ()) for message in image_messages} == {
        (expected_path,)
    }


def test_gemini_parser_classifies_user_image_and_repeated_reference(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    conv_dir = merged / "account-1" / "conversations"
    asset_dir = merged / "account-1" / "assets"
    manifest_dir = tmp_path / "raw" / "Gemini" / "account-1"
    conv_dir.mkdir(parents=True)
    asset_dir.mkdir(parents=True)
    manifest_dir.mkdir(parents=True)
    image_url = "https://lh3.googleusercontent.com/uploaded-image"
    (asset_dir / "upload.png").write_bytes(b"upload")
    (manifest_dir / "assets_manifest.json").write_text(json.dumps({"key": {
        "url": image_url, "conv_id": "c_upload", "content_type": "image/png",
        "size": 6, "filename": "upload.png",
    }}))
    turns = []
    for prompt in ("first", "reuse"):
        turn = _make_turn(prompt, "ok", 1762000000)
        turn[2].append([image_url])
        turns.append(turn)
    (conv_dir / "c_upload.json").write_text(json.dumps({
        "uuid": "c_upload", "raw": [turns, None, None, []],
    }))

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    assert len(parser.assets) == 1
    assert parser.assets[0].asset_kind == "attachment"
    assert parser.assets[0].asset_origin == "user"
    assert len(parser.asset_links) == 2
    assert {link.role for link in parser.asset_links} == {"input"}
    assert {link.message_id for link in parser.asset_links} == {
        "account-1_c_upload_t0_user", "account-1_c_upload_t1_user",
    }


def test_gemini_parser_emits_deep_research_report_at_observed_message(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    conv_dir = merged / "account-1" / "conversations"
    report_dir = merged / "account-1" / "assets" / "deep_research" / "c_report"
    conv_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    turn = _make_turn("research", "summary", 1762000000)
    (conv_dir / "c_report.json").write_text(json.dumps({
        "uuid": "c_report", "raw": [[turn], None, None, []],
    }))
    report = report_dir / "report_00_deadbeef.md"
    report.write_text("# Preserved report\n\nBody")
    report.with_suffix(".md.meta.json").write_text(json.dumps({
        "conv_id": "c_report",
        "source_path": "[0][0][3][0][0][30][0][4]",
        "title": "Preserved report",
        "content_size": report.stat().st_size,
    }))

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    report_assets = [asset for asset in parser.assets if asset.mime_type == "text/markdown"]
    assert len(report_assets) == 1
    assert report_assets[0].asset_kind == "output"
    assert report_assets[0].asset_origin == "assistant"
    link = next(link for link in parser.asset_links if link.asset_id == report_assets[0].asset_id)
    assert link.message_id == "account-1_c_report_t0_asst"
    assert link.role == "output"
    assert link.ordinal == 0


def test_gemini_parser_keeps_unreferenced_manifest_asset_unavailable(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    conv_dir = merged / "account-1" / "conversations"
    manifest_dir = tmp_path / "raw" / "Gemini" / "account-1"
    conv_dir.mkdir(parents=True)
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "assets_manifest.json").write_text(json.dumps({"stable-key": {
        "url": "https://lh3.googleusercontent.com/no-longer-referenced?secret=yes",
        "conv_id": "c_old", "content_type": "image/png", "size": 123,
        "filename": "missing.png",
    }}))

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    assert len(parser.assets) == 1
    asset = parser.assets[0]
    assert asset.asset_origin == "unknown"
    assert asset.asset_kind == "other"
    assert asset.asset_path is None
    assert asset.is_binary_available is False
    assert parser.asset_links == []
    assert "http" not in (asset.metadata_json or "")


def test_gemini_parser_does_not_link_referenced_missing_manifest_asset(tmp_path: Path):
    merged = tmp_path / "merged" / "Gemini"
    conv_dir = merged / "account-1" / "conversations"
    manifest_dir = tmp_path / "raw" / "Gemini" / "account-1"
    conv_dir.mkdir(parents=True)
    manifest_dir.mkdir(parents=True)
    image_url = "https://lh3.googleusercontent.com/missing"
    (manifest_dir / "assets_manifest.json").write_text(json.dumps({"stable-key": {
        "url": image_url, "conv_id": "c_missing", "content_type": "image/png",
        "size": 123, "filename": "missing.png",
    }}))
    turn = _make_turn("draw", "done", 1762000000, images=[image_url])
    (conv_dir / "c_missing.json").write_text(json.dumps({
        "uuid": "c_missing", "raw": [[turn], None, None, []],
    }))

    parser = GeminiParser(merged_root=merged)
    parser.parse(merged)

    assert len(parser.assets) == 1
    assert parser.assets[0].is_binary_available is False
    assert parser.asset_links == []
    assert all(message.asset_paths is None for message in parser.messages)
