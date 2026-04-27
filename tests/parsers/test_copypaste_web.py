import pytest
import pandas as pd
from pathlib import Path
from src.parsers.copypaste_web import CopypasteWebParser


FIXTURE_GPT = """como interpretar esse resultado:
codigo aqui

ChatGPT said:

Vamos interpretar isso com rigor.
Mais detalhes da resposta.
"""

FIXTURE_QWEN = """como interpretar esse resultado:
codigo aqui

Qwen3-Max
10:10 PM

Você está interpretando os resultados de uma análise.
Continuação da resposta.

Qwen3-Max
10:32 PM

Obrigado por compartilhar mais contexto.
"""

FIXTURE_MANUAL_MARKERS = """--- USER ---
como interpretar esse resultado:
codigo aqui

--- ASSISTANT ---
Analisando os gráficos, aqui está a interpretação.
Continuação da resposta.
"""

FIXTURE_GEMINI_HEADER = """Conversation with Gemini
como interpretar esse resultado:
codigo aqui



Olá! A imagem e o texto mostram uma análise de clustering.
Continuação da resposta do Gemini.
"""


def _write_fixture(tmp_path, filename, content):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return tmp_path


def test_copypaste_gpt(tmp_path):
    _write_fixture(tmp_path, "GPT.txt", FIXTURE_GPT)
    parser = CopypasteWebParser()
    parser.parse(tmp_path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2
    conv = parser.conversations[0]
    assert conv.source == "chatgpt"
    assert conv.conversation_id == "manual_copypaste_gpt"
    msgs = parser.messages
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"
    assert "interpretar" in msgs[0].content
    assert "rigor" in msgs[1].content


def test_copypaste_qwen(tmp_path):
    _write_fixture(tmp_path, "QWEEN.txt", FIXTURE_QWEN)
    parser = CopypasteWebParser()
    parser.parse(tmp_path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 3
    conv = parser.conversations[0]
    assert conv.source == "qwen"
    roles = [m.role for m in parser.messages]
    assert roles == ["user", "assistant", "assistant"]


def test_copypaste_manual_markers(tmp_path):
    _write_fixture(tmp_path, "CLAUDE.txt", FIXTURE_MANUAL_MARKERS)
    parser = CopypasteWebParser()
    parser.parse(tmp_path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2
    conv = parser.conversations[0]
    assert conv.source == "claude_ai"


def test_copypaste_gemini_header(tmp_path):
    _write_fixture(tmp_path, "GEMINI-hello.txt", FIXTURE_GEMINI_HEADER)
    parser = CopypasteWebParser()
    parser.parse(tmp_path)
    assert len(parser.conversations) == 1
    assert len(parser.messages) == 2
    conv = parser.conversations[0]
    assert conv.source == "gemini"
    assert conv.conversation_id == "manual_copypaste_gemini-hello"
    roles = [m.role for m in parser.messages]
    assert roles == ["user", "assistant"]


def test_copypaste_mode(tmp_path):
    _write_fixture(tmp_path, "GPT.txt", FIXTURE_GPT)
    parser = CopypasteWebParser()
    parser.parse(tmp_path)
    assert parser.conversations[0].mode == "chat"


def test_copypaste_sequences(tmp_path):
    _write_fixture(tmp_path, "GPT.txt", FIXTURE_GPT)
    parser = CopypasteWebParser()
    parser.parse(tmp_path)
    seqs = [m.sequence for m in parser.messages]
    assert seqs == [1, 2]


def test_copypaste_no_events(tmp_path):
    _write_fixture(tmp_path, "GPT.txt", FIXTURE_GPT)
    parser = CopypasteWebParser()
    parser.parse(tmp_path)
    assert len(parser.events) == 0
