from src.importers.manual.identity import (
    manual_event_id,
    manual_message_id,
    normalize_manual_text,
)


def test_normalize_manual_text_uses_nfc_and_lf():
    assert normalize_manual_text("cafe\u0301\r\nlinha\r") == "café\nlinha\n"


def test_manual_message_id_is_deterministic_and_content_sensitive():
    first = manual_message_id("conv", "user", "olá\r\n", 0)

    assert first == manual_message_id("conv", "user", "olá\n", 0)
    assert first != manual_message_id("conv", "assistant", "olá\n", 0)
    assert first != manual_message_id("conv", "user", "outro", 0)
    assert first != manual_message_id("conv", "user", "olá\n", 1)


def test_manual_event_id_is_deterministic_and_parent_sensitive():
    first = manual_event_id("msg", "tool_call", "Bash", "pwd", 0)

    assert first == manual_event_id("msg", "tool_call", "Bash", "pwd", 0)
    assert first != manual_event_id("other", "tool_call", "Bash", "pwd", 0)
    assert first != manual_event_id("msg", "tool_call", "Bash", "ls", 0)

