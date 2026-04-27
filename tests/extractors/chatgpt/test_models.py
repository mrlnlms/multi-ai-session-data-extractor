"""Testes das dataclasses de modelo do chatgpt extractor."""

import pytest

from src.extractors.chatgpt.models import (
    ConversationMeta,
    ProjectMeta,
    VoiceCapture,
    VoiceMessage,
    CaptureOptions,
    CaptureReport,
)


def test_conversation_meta_required_fields():
    meta = ConversationMeta(
        id="abc-123",
        title="Test conv",
        create_time=1740000000.0,
        update_time=1740000500.0,
        project_id=None,
        archived=False,
    )
    assert meta.id == "abc-123"
    assert meta.archived is False


def test_project_meta_with_discovery_method():
    proj = ProjectMeta(id="g-p-abc", name="Studies", discovered_via="next_data")
    assert proj.discovered_via == "next_data"


def test_voice_message_user_turn():
    msg = VoiceMessage(
        dom_sequence=0,
        role="user",
        text="Hello world",
        duration_seconds=8,
        was_voice=True,
    )
    assert msg.was_voice is True
    assert msg.duration_seconds == 8


def test_voice_message_assistant_no_duration():
    msg = VoiceMessage(
        dom_sequence=1,
        role="assistant",
        text="Response",
        duration_seconds=None,
        was_voice=False,
    )
    assert msg.duration_seconds is None
    assert msg.was_voice is False


def test_capture_options_defaults():
    opts = CaptureOptions()
    assert opts.skip_voice is False
    assert opts.dry_run is False


def test_capture_options_overrides():
    opts = CaptureOptions(skip_voice=True, dry_run=True)
    assert opts.skip_voice is True
    assert opts.dry_run is True
