import json
import zipfile
import pytest
from pathlib import Path
from src.parsers.chatgpt import ChatGPTParser
import pandas as pd


FIXTURE = {
    "export_date": "2026-03-27T18:13:46.494Z",
    "tool": "GPT2Claude Migration Kit v2.7",
    "format_version": 7,
    "total_conversations": 2,
    "conversations": [
        {
            "id": "conv-gpt1",
            "title": "Simple chat",
            "create_time": "2025-08-01T10:00:00Z",
            "update_time": "2025-08-01T10:05:00Z",
            "model": "gpt-4o",
            "message_count": 2,
            "messages": [
                {"role": "user", "content": "Hello", "timestamp": 1722502800.0},
                {"role": "assistant", "content": "Hi there!", "timestamp": 1722502810.0},
            ],
        },
        {
            "id": "conv-gpt2",
            "title": "Research chat",
            "create_time": "2025-09-15T20:00:00Z",
            "update_time": "2025-09-15T20:10:00Z",
            "model": "gpt-4o",
            "message_count": 3,
            "messages": [
                {"role": "user", "content": "Search for mixed methods", "timestamp": 1726430400.0},
                {"role": "tool", "content": "{\"content_type\":\"super_widget\",\"urls\":[\"https://example.com\"]}", "timestamp": 1726430405.0, "model": "research"},
                {"role": "assistant", "content": "Here are the results...", "timestamp": 1726430410.0},
            ],
        },
    ],
}


def _write_fixture(tmp_path, data):
    p = tmp_path / "export.json"
    p.write_text(json.dumps(data))
    return p


def test_chatgpt_simple(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ChatGPTParser()
    parser.parse(path)
    assert len(parser.conversations) == 2
    conv = parser.conversations[0]
    assert conv.conversation_id == "conv-gpt1"
    assert conv.source == "chatgpt"
    assert conv.title == "Simple chat"
    assert conv.model == "gpt-4o"
    assert conv.mode == "chat"


def test_chatgpt_tool_message_merged(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ChatGPTParser()
    parser.parse(path)
    conv2_msgs = [m for m in parser.messages if m.conversation_id == "conv-gpt2"]
    assert len(conv2_msgs) == 2
    asst = conv2_msgs[1]
    assert asst.role == "assistant"
    assert asst.content == "Here are the results..."
    assert asst.tool_results is not None
    assert "super_widget" in asst.tool_results


def test_chatgpt_research_mode(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ChatGPTParser()
    parser.parse(path)
    conv = parser.conversations[1]
    assert conv.mode == "research"


def test_chatgpt_timestamps_from_float(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ChatGPTParser()
    parser.parse(path)
    msg = parser.messages[0]
    # epoch 1722502800 = 2024-08-01 09:00 UTC = 06:00 BRT
    assert msg.created_at == pd.Timestamp("2024-08-01 06:00:00")


def test_chatgpt_url_generated(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ChatGPTParser()
    parser.parse(path)
    assert parser.conversations[0].url == "https://chatgpt.com/c/conv-gpt1"


def _make_dalle_zip(tmp_path):
    """Cria um zip DALL-E fake com estrutura real."""
    zip_path = tmp_path / "dalle.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        # Standalone generation com caption
        z.writestr(
            "personal/dallelabs/user-test/generations/generation-abc123/caption.txt",
            "A cyberpunk city",
        )
        z.writestr(
            "personal/dallelabs/user-test/generations/generation-abc123/image.png",
            b"fake-png",
        )
        z.writestr(
            "personal/dallelabs/user-test/generations/generation-abc123/image.webp",
            b"fake-webp",
        )
        # In-conversation (conv_id com hex timestamp valido: 2024-11-11 ~20:17)
        z.writestr(
            "personal/dallelabs/user-data/chatgptgenerations/user-test/conversations/67326661-4c64-800c-a22b-fac1da33674e/img1.webp",
            b"fake-webp",
        )
    return zip_path


def test_parse_dalle_standalone(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ChatGPTParser()
    parser.parse(path)
    dalle_zip = _make_dalle_zip(tmp_path)
    parser.parse_dalle(dalle_zip)

    dalle_convs = [c for c in parser.conversations if c.mode == "dalle"]
    assert len(dalle_convs) == 2  # 1 standalone + 1 in_conversation

    standalone = [c for c in dalle_convs if c.conversation_id.startswith("dalle-standalone")]
    assert len(standalone) == 1
    assert "cyberpunk" in standalone[0].title.lower()
    assert standalone[0].model == "dall-e"

    # Mensagens: standalone tem user (prompt) + assistant (geração)
    standalone_msgs = [m for m in parser.messages if m.conversation_id == standalone[0].conversation_id]
    assert len(standalone_msgs) == 2
    assert standalone_msgs[0].role == "user"
    assert standalone_msgs[0].content == "A cyberpunk city"
    assert standalone_msgs[1].role == "assistant"
    assert standalone_msgs[1].content_types == "image_generation"


def test_parse_dalle_in_conversation_orphan(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE)
    parser = ChatGPTParser()
    parser.parse(path)
    dalle_zip = _make_dalle_zip(tmp_path)
    parser.parse_dalle(dalle_zip)

    orphan = [c for c in parser.conversations if c.conversation_id == "67326661-4c64-800c-a22b-fac1da33674e"]
    assert len(orphan) == 1
    assert orphan[0].mode == "dalle"
    assert orphan[0].url == "https://chatgpt.com/c/67326661-4c64-800c-a22b-fac1da33674e"
    # Timestamp decodificado do hex
    assert orphan[0].created_at.year == 2024


def test_decode_hex_ts():
    assert ChatGPTParser._decode_hex_ts("67326661-4c64-800c").year == 2024
    assert pd.isna(ChatGPTParser._decode_hex_ts("12bebd92-da0a-49b9"))  # fora do range
    assert pd.isna(ChatGPTParser._decode_hex_ts("zzzzzzzz-invalid"))
