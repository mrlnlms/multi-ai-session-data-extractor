"""Testes do orchestrator — fluxo end-to-end com todos os módulos mockados."""

import pytest
from pathlib import Path

from src.extractors.chatgpt.models import CaptureOptions, ConversationMeta
from src.extractors.chatgpt.orchestrator import run_capture


async def test_run_capture_produces_raw_file(tmp_path, mocker):
    """Fluxo minimo: discovery retorna 2 convs → fetch baixa → salva raw.json."""
    # Mock do launch_persistent_context
    mock_context = mocker.AsyncMock()
    mock_page = mocker.AsyncMock()
    mock_context.new_page.return_value = mock_page
    mock_context.request = mocker.AsyncMock()

    # Mock do async_playwright — forma simplificada
    mock_p = mocker.MagicMock()
    mock_p.chromium.launch_persistent_context = mocker.AsyncMock(return_value=mock_context)
    mock_playwright_context = mocker.MagicMock()
    mock_playwright_context.__aenter__ = mocker.AsyncMock(return_value=mock_p)
    mock_playwright_context.__aexit__ = mocker.AsyncMock(return_value=None)
    mocker.patch(
        "src.extractors.chatgpt.orchestrator.async_playwright",
        return_value=mock_playwright_context,
    )

    # Mock discover_all — retorna tupla (metas, project_names)
    mocker.patch(
        "src.extractors.chatgpt.orchestrator.discover_all",
        new_callable=mocker.AsyncMock,
        return_value=(
            [
                ConversationMeta(id="a", title="A", create_time=1.0, update_time=2.0,
                               project_id=None, archived=False),
            ],
            {},
        ),
    )

    # Mock fetch_all
    mocker.patch(
        "src.extractors.chatgpt.orchestrator.fetch_all",
        new_callable=mocker.AsyncMock,
        return_value={"a": {"id": "a", "mapping": {}}},
    )

    # Mock fetch_memories e fetch_instructions
    mock_client_inst = mocker.AsyncMock()
    mock_client_inst.fetch_memories.return_value = "# Memories\n\n- fact 1"
    mock_client_inst.fetch_instructions.return_value = {"about_user": "dev"}
    mocker.patch(
        "src.extractors.chatgpt.orchestrator.ChatGPTAPIClient",
        return_value=mock_client_inst,
    )

    # Mock detect_voice_candidates → sem voice
    mocker.patch(
        "src.extractors.chatgpt.orchestrator.detect_voice_candidates",
        return_value=[],
    )

    output_dir = tmp_path / "ChatGPT Data 2026-04-23"
    options = CaptureOptions(skip_voice=False)
    report = await run_capture(output_dir, options)

    assert (output_dir / "chatgpt_raw.json").exists()
    assert (output_dir / "chatgpt_memories.md").exists()
    assert (output_dir / "chatgpt_instructions.json").exists()
    assert (output_dir / "capture_log.jsonl").exists()
    assert (output_dir / "LAST_CAPTURE.md").exists()
    assert report.discovery_counts["total"] == 1
