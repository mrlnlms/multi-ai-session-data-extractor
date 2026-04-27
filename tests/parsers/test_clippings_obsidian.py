import pytest
import pandas as pd
from pathlib import Path
from src.parsers.clippings_obsidian import ClippingsObsidianParser


FIXTURE_CHATGPT = """---
title: "ChatGPT"
source: "https://chatgpt.com/c/abc12345-1234-5678-9abc-def012345678"
author:
  - "[[ChatGPT]]"
published:
created: 2025-07-09
description: "ChatGPT is your AI chatbot."
tags:
  - "clippings"
---
> Qual a diferença entre UX e UI?

UX (User Experience) foca na experiência completa do usuário...

> E o que é service design?

Service design é uma abordagem que considera...
"""

FIXTURE_CLAUDE = """---
title: "Claude"
source: "https://claude.ai/chat/c915b705-95ae-4281-9d4b-d094ecd74d18"
author:
  - "[[Claude]]"
published:
created: 2025-05-15
description: "Claude is an AI assistant."
tags:
  - "clippings"
---
> Quero construir uma ferramenta de pesquisa qualitativa.

Que projeto interessante! Vou te ajudar a pensar na arquitetura...
"""

FIXTURE_MULTILINE_BLOCKQUOTE = """---
title: "ChatGPT"
source: "https://chatgpt.com/c/11111111-2222-3333-4444-555555555555"
author:
  - "[[ChatGPT]]"
published:
created: 2025-08-12
description: "ChatGPT"
tags:
  - "clippings"
---
> Primeira linha do prompt
> segunda linha do prompt
> terceira linha

Resposta do assistant aqui.
Continuação da resposta.
"""


def _write_fixture(tmp_path, filename, content):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return tmp_path


def test_clippings_basic_chatgpt(tmp_path):
    _write_fixture(tmp_path, "2025-07-09 - Test Chat.md", FIXTURE_CHATGPT)
    parser = ClippingsObsidianParser()
    parser.parse(tmp_path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 4
    conv = parser.conversations[0]
    assert conv.conversation_id == "abc12345-1234-5678-9abc-def012345678"
    assert conv.source == "chatgpt"
    assert conv.title == "Test Chat"
    # date sem hora no YAML → interpretada como UTC → BRT-3h = dia anterior 21:00
    assert conv.created_at == pd.Timestamp("2025-07-08 21:00:00")
    assert conv.updated_at == pd.Timestamp("2025-07-08 21:00:00")
    assert conv.message_count == 4
    assert conv.model is None


def test_clippings_claude_source(tmp_path):
    _write_fixture(tmp_path, "2025-05-15 - Qualitative Tool.md", FIXTURE_CLAUDE)
    parser = ClippingsObsidianParser()
    parser.parse(tmp_path)
    conv = parser.conversations[0]
    assert conv.source == "claude_ai"
    assert conv.conversation_id == "c915b705-95ae-4281-9d4b-d094ecd74d18"


def test_clippings_roles_alternate(tmp_path):
    _write_fixture(tmp_path, "2025-07-09 - Test Chat.md", FIXTURE_CHATGPT)
    parser = ClippingsObsidianParser()
    parser.parse(tmp_path)
    roles = [m.role for m in parser.messages]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_clippings_sequence(tmp_path):
    _write_fixture(tmp_path, "2025-07-09 - Test Chat.md", FIXTURE_CHATGPT)
    parser = ClippingsObsidianParser()
    parser.parse(tmp_path)
    seqs = [m.sequence for m in parser.messages]
    assert seqs == [1, 2, 3, 4]


def test_clippings_multiline_blockquote(tmp_path):
    _write_fixture(tmp_path, "2025-08-12 - Multiline.md", FIXTURE_MULTILINE_BLOCKQUOTE)
    parser = ClippingsObsidianParser()
    parser.parse(tmp_path)
    assert len(parser.messages) == 2
    user_msg = parser.messages[0]
    assert "Primeira linha" in user_msg.content
    assert "terceira linha" in user_msg.content
    assert user_msg.role == "user"


def test_clippings_multiple_files(tmp_path):
    _write_fixture(tmp_path, "2025-07-09 - Chat1.md", FIXTURE_CHATGPT)
    _write_fixture(tmp_path, "2025-05-15 - Chat2.md", FIXTURE_CLAUDE)
    parser = ClippingsObsidianParser()
    parser.parse(tmp_path)
    assert len(parser.conversations) == 2
    sources = {c.source for c in parser.conversations}
    assert sources == {"chatgpt", "claude_ai"}


def test_clippings_content_stripped(tmp_path):
    _write_fixture(tmp_path, "2025-07-09 - Test Chat.md", FIXTURE_CHATGPT)
    parser = ClippingsObsidianParser()
    parser.parse(tmp_path)
    user_msg = parser.messages[0]
    assert not user_msg.content.startswith(">")
    assert "Qual a diferença" in user_msg.content


def test_clippings_no_events(tmp_path):
    _write_fixture(tmp_path, "2025-07-09 - Test Chat.md", FIXTURE_CHATGPT)
    parser = ClippingsObsidianParser()
    parser.parse(tmp_path)
    assert len(parser.events) == 0
