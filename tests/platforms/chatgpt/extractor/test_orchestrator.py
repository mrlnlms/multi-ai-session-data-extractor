"""Testes do orchestrator — fluxo end-to-end com todos os módulos mockados."""

import pytest
import json
from pathlib import Path

from src.platforms.chatgpt.extractor.models import CaptureOptions, ConversationMeta, ProjectMeta
from src.platforms.chatgpt.extractor.orchestrator import run_capture


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
async def test_run_capture_produces_raw_file(tmp_path, mocker, fallback, dry_run):
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
        "src.platforms.chatgpt.extractor.orchestrator.async_playwright",
        return_value=mock_playwright_context,
    )

    # Mock discover_all — retorna tupla (metas, project_names)
    mocker.patch(
        "src.platforms.chatgpt.extractor.orchestrator.discover_all",
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
        "src.platforms.chatgpt.extractor.orchestrator.fetch_all",
        new_callable=mocker.AsyncMock,
        return_value={"a": {"id": "a", "mapping": {}}},
    )

    # Mock fetch_memories e fetch_instructions
    mock_client_inst = mocker.AsyncMock()
    mock_client_inst.fetch_memories.return_value = {"memories": [{"id": "m1", "content": "fact 1"}]}
    mock_client_inst.fetch_instructions.return_value = {"about_user": "dev"}
    mock_client_inst.fetch_memory_summary_checksum.return_value = {"isStale": False}
    mock_client_inst.fetch_memory_summary.return_value = 'event: done\ndata: {"sections": []}\n\n'
    mock_client_inst.list_projects.return_value = [ProjectMeta(
        id="g-p-test", name="Test", discovered_via="sidebar",
    )]
    mock_client_inst.fetch_project_detail.return_value = {
        "gizmo": {"id": "g-p-test", "instructions": "Test", "memory_scope": "global",
                  "memory_enabled": True}, "files": [],
    }
    mock_client_cls = mocker.patch(
        "src.platforms.chatgpt.extractor.orchestrator.ChatGPTAPIClient",
        return_value=mock_client_inst,
    )

    # Mock detect_voice_candidates → sem voice
    mocker.patch(
        "src.platforms.chatgpt.extractor.orchestrator.detect_voice_candidates",
        return_value=[],
    )

    output_dir = tmp_path / "ChatGPT Data 2026-04-23"
    if fallback:
        output_dir.mkdir()
        (output_dir / "chatgpt_raw.json").write_text(json.dumps({"conversations": {"a": {"id": "a"}}}))
        mocker.patch("src.platforms.chatgpt.extractor.orchestrator._get_max_known_discovery", return_value=20)
        mocker.patch(
            "src.platforms.chatgpt.extractor.orchestrator.refetch_known_via_page",
            new_callable=mocker.AsyncMock,
            return_value={"total": 1, "updated": 0, "errors": 0},
        )
    options = CaptureOptions(skip_voice=False, dry_run=dry_run)
    report = await run_capture(output_dir, options)

    if dry_run:
        mock_client_inst.fetch_memories.assert_not_awaited()
        mock_client_inst.fetch_instructions.assert_not_awaited()
        mock_client_inst.fetch_memory_summary.assert_not_awaited()
        mock_client_inst.fetch_memory_summary_checksum.assert_not_awaited()
        mock_client_inst.fetch_project_detail.assert_not_awaited()
        assert not (output_dir / "_account_memory").exists()
        return

    assert (output_dir / "chatgpt_raw.json").exists()
    assert (output_dir / "chatgpt_memories.md").exists()
    assert (output_dir / "chatgpt_memories.json").exists()
    assert len(list((output_dir / "_account_memory").glob("*/*/capture.json"))) == 4
    assert len(list((output_dir / "_project_settings" / "g-p-test").glob("*/capture.json"))) == 1
    assert (output_dir / "chatgpt_memory_summary.json").exists()
    assert (output_dir / "chatgpt_instructions.json").exists()
    assert (output_dir / "capture_log.jsonl").exists()
    assert (output_dir / "LAST_CAPTURE.md").exists()
    assert report.discovery_counts["total"] == 1
    assert report.mode == ("refetch_known_fallback" if fallback else "incremental")
    mock_page.goto.assert_awaited_once_with(
        "https://chatgpt.com/",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    mock_client_cls.assert_called_once_with(mock_context.request, page=mock_page)
