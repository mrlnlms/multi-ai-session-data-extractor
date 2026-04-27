"""Testes de dom_voice.py — detecao e DOM scrape de voice mode."""

import pytest

from src.extractors.chatgpt.dom_voice import capture_voice_dom, detect_voice_candidates
from tests.extractors.chatgpt.conftest import load_fixture


def test_detect_voice_candidates_flags_above_threshold():
    raw = {"conversations": {"conv-voice": load_fixture("conversation_with_voice_placeholders")}}
    candidates = detect_voice_candidates(raw, threshold=0.5)
    assert "conv-voice" in candidates


def test_detect_voice_candidates_ignores_mostly_text():
    raw = {"conversations": {"conv-normal": load_fixture("conversation_mostly_text")}}
    candidates = detect_voice_candidates(raw, threshold=0.5)
    assert candidates == []


def test_detect_voice_candidates_custom_threshold():
    """Conv com 66% placeholder passa em threshold 0.5 mas nao em 0.9."""
    raw = {"conversations": {"conv-voice": load_fixture("conversation_with_voice_placeholders")}}
    assert "conv-voice" in detect_voice_candidates(raw, threshold=0.5)
    assert "conv-voice" not in detect_voice_candidates(raw, threshold=0.9)


@pytest.mark.asyncio
async def test_capture_voice_dom_calls_page_goto_per_conv(mocker):
    """Pra cada conv_id, navega + extrai mensagens."""
    mock_page = mocker.AsyncMock()
    # Simula page.evaluate retornando lista de msgs
    mock_page.evaluate.return_value = [
        {"dom_sequence": 0, "role": "user", "text": "Hello", "duration_seconds": 5, "was_voice": True},
        {"dom_sequence": 1, "role": "assistant", "text": "Hi", "duration_seconds": None, "was_voice": False},
    ]
    mocker.patch("src.extractors.chatgpt.dom_voice.asyncio.sleep", new_callable=mocker.AsyncMock)

    captures = await capture_voice_dom(mock_page, ["conv-1"])

    assert "conv-1" in captures
    cap = captures["conv-1"]
    assert cap.conversation_id == "conv-1"
    assert len(cap.messages) == 2
    assert cap.messages[0].was_voice is True
    assert cap.messages[0].duration_seconds == 5
    mock_page.goto.assert_called_once()


@pytest.mark.asyncio
async def test_capture_voice_dom_skips_convs_without_mic(mocker):
    """Se page.evaluate retorna msgs mas NENHUMA com was_voice=True, retorna None pra essa conv."""
    mock_page = mocker.AsyncMock()
    mock_page.evaluate.return_value = [
        {"dom_sequence": 0, "role": "user", "text": "Hello", "duration_seconds": None, "was_voice": False},
    ]
    mocker.patch("src.extractors.chatgpt.dom_voice.asyncio.sleep", new_callable=mocker.AsyncMock)

    captures = await capture_voice_dom(mock_page, ["conv-screenshot"])
    # Conv nao era voice de verdade (era screenshot) — omitida
    assert "conv-screenshot" not in captures


@pytest.mark.asyncio
async def test_capture_voice_dom_handles_exception_continues(mocker):
    """Se uma conv falha no page.goto, continua pras outras."""
    mock_page = mocker.AsyncMock()
    mock_page.goto.side_effect = [Exception("network"), None]
    mock_page.evaluate.return_value = [
        {"dom_sequence": 0, "role": "user", "text": "Hi", "duration_seconds": 3, "was_voice": True},
    ]
    mocker.patch("src.extractors.chatgpt.dom_voice.asyncio.sleep", new_callable=mocker.AsyncMock)

    captures = await capture_voice_dom(mock_page, ["conv-fail", "conv-ok"])
    assert "conv-fail" not in captures
    assert "conv-ok" in captures
