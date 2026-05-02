"""Testes do GeminiParser v3 — schema raw posicional (batchexecute)."""

import json
from pathlib import Path

import pytest

from src.parsers.gemini import GeminiParser
from src.parsers._gemini_helpers import (
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
    for acc in [1, 2]:
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
    assert ids == {"account-1_c_dup", "account-2_c_dup"}


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
