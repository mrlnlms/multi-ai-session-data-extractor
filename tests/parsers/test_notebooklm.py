import json
import pytest
from pathlib import Path
from src.parsers.notebooklm import NotebookLMParser
import pandas as pd


FIXTURE_7COL = """\
# Inventario NotebookLM

| # | Titulo | Criado | Atualizado | Sources | Fontes | Link |
|---|--------|--------|------------|---------|--------|------|
| 1 | 📘 Geometria do Dialogo | 2026-03-25 | 2026-03-25 | 4 | fonte1, fonte2 | [abrir](https://notebooklm.google.com/notebook/1858be29-9c27-4c14-a4ce-e463990c7044) |
| 2 | 🧩 Defining Visual Analysis | 2025-12-06 | 2026-03-24 | 1 | fonte3 | [abrir](https://notebooklm.google.com/notebook/71d75656-5e55-4d8d-9150-c35681600989) |
"""

FIXTURE_5COL = """\
# Inventario NotebookLM marloonlemes

| # | Titulo | Data | Sources | Link |
|---|--------|------|---------|------|
| 1 | Quantitizar o Quali | 25 de mai. de 2025 | 1 | [abrir](https://notebooklm.google.com/notebook/50772739-c5e7-4dc9-a6a9-ca99a6f24cac) |
| 2 | Transferencia Operacional | 10 de dez. de 2025 | 5 | [abrir](https://notebooklm.google.com/notebook/a84f652b-66f7-42cb-8976-51c8b2a17cf9) |
"""


def _write_fixture(tmp_path, content, filename="inventario.md"):
    p = tmp_path / filename
    p.write_text(content)
    return p


def test_notebooklm_7col(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_7COL)
    parser = NotebookLMParser(account="pessoal")
    parser.parse(path)

    assert len(parser.conversations) == 2
    assert len(parser.messages) == 0

    conv = parser.conversations[0]
    assert conv.conversation_id == "1858be29-9c27-4c14-a4ce-e463990c7044"
    assert conv.source == "notebooklm"
    assert conv.title == "📘 Geometria do Dialogo"
    assert conv.message_count == 0
    assert conv.account == "pessoal"
    # "2026-03-25" sem TZ → UTC → BRT = dia 24 às 21:00
    assert conv.created_at == pd.Timestamp("2026-03-24 21:00:00")


def test_notebooklm_5col(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_5COL)
    parser = NotebookLMParser(account="trabalho")
    parser.parse(path)

    assert len(parser.conversations) == 2

    conv = parser.conversations[0]
    assert conv.conversation_id == "50772739-c5e7-4dc9-a6a9-ca99a6f24cac"
    assert conv.account == "trabalho"
    assert conv.title == "Quantitizar o Quali"
    assert conv.message_count == 0


def test_notebooklm_5col_date_parsing(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_5COL)
    parser = NotebookLMParser(account="trabalho")
    parser.parse(path)

    conv = parser.conversations[0]
    assert conv.created_at == pd.Timestamp("2025-05-25")


def test_notebooklm_uuid_from_link(tmp_path):
    path = _write_fixture(tmp_path, FIXTURE_7COL)
    parser = NotebookLMParser(account="pessoal")
    parser.parse(path)

    ids = [c.conversation_id for c in parser.conversations]
    assert ids == [
        "1858be29-9c27-4c14-a4ce-e463990c7044",
        "71d75656-5e55-4d8d-9150-c35681600989",
    ]


def _create_notebook_dir(tmp_path, uuid, notebook_data, chat_data=None, briefs=None):
    """Helper: cria estrutura de diretorio com notebook.json, chat.json e briefs."""
    nb_dir = tmp_path / uuid
    nb_dir.mkdir()
    (nb_dir / "notebook.json").write_text(json.dumps(notebook_data, ensure_ascii=False))
    if chat_data:
        (nb_dir / "chat.json").write_text(json.dumps(chat_data, ensure_ascii=False))
    if briefs:
        audio_dir = nb_dir / "audio"
        audio_dir.mkdir()
        for i, content in enumerate(briefs):
            (audio_dir / f"brief-{i}_brief.md").write_text(content)
    return nb_dir


def test_parse_downloads_extracts_guides(tmp_path):
    uuid = "aaaa1111-2222-3333-4444-555566667777"
    nb_data = {
        "uuid": uuid,
        "title": "Test Notebook",
        "emoji": "📘",
        "sources": [
            {"uuid": "src-1", "name": "paper.pdf"},
            {"uuid": "src-2", "name": "notes.md"},
        ],
        "guide": {
            "summary": "Este notebook analisa papers academicos.",
            "questions": ["Pergunta 1?", "Pergunta 2?"],
        },
    }
    _create_notebook_dir(tmp_path, uuid, nb_data)

    parser = NotebookLMParser(account="test")
    _add_conversation(parser, uuid, "Test Notebook")
    parser.parse_downloads(tmp_path)

    assert len(parser.guides) == 1
    g = parser.guides[0]
    assert g.conversation_id == uuid
    assert g.guide_summary == "Este notebook analisa papers academicos."
    assert g.source_count == 2
    assert json.loads(g.source_names) == ["paper.pdf", "notes.md"]


def test_parse_downloads_extracts_sources(tmp_path):
    uuid = "bbbb1111-2222-3333-4444-555566667777"
    nb_data = {
        "uuid": uuid,
        "title": "Test",
        "emoji": "",
        "sources": [
            {"uuid": "src-a", "name": "relatorio.pdf"},
            {"uuid": "src-b", "name": "dados.csv"},
            {"uuid": "src-c", "name": "imagem.png"},
        ],
        "guide": {"summary": "", "questions": []},
    }
    _create_notebook_dir(tmp_path, uuid, nb_data)

    parser = NotebookLMParser(account="test")
    _add_conversation(parser, uuid, "Test")
    parser.parse_downloads(tmp_path)

    assert len(parser.sources) == 3
    names = [s.source_name for s in parser.sources]
    assert names == ["relatorio.pdf", "dados.csv", "imagem.png"]


def test_parse_downloads_no_guide(tmp_path):
    uuid = "cccc1111-2222-3333-4444-555566667777"
    nb_data = {
        "uuid": uuid,
        "title": "Empty",
        "emoji": "",
        "sources": [],
        "guide": {},
    }
    _create_notebook_dir(tmp_path, uuid, nb_data)

    parser = NotebookLMParser(account="test")
    parser.parse_downloads(tmp_path)

    assert len(parser.guides) == 0
    assert len(parser.sources) == 0


def test_guides_df_columns(tmp_path):
    uuid = "dddd1111-2222-3333-4444-555566667777"
    nb_data = {
        "uuid": uuid,
        "title": "DF Test",
        "sources": [{"uuid": "s1", "name": "doc.pdf"}],
        "guide": {"summary": "Resumo teste."},
    }
    _create_notebook_dir(tmp_path, uuid, nb_data)

    parser = NotebookLMParser(account="test")
    _add_conversation(parser, uuid, "DF Test")
    parser.parse_downloads(tmp_path)

    df = parser.guides_df()
    assert list(df.columns) == ["conversation_id", "guide_summary", "source_count", "source_names"]
    assert len(df) == 1


def _add_conversation(parser, uuid, title="Test"):
    """Helper: registra uma conversa no parser pra simular inventario."""
    from src.schema.models import Conversation
    parser.conversations.append(Conversation(
        conversation_id=uuid,
        source="notebooklm",
        title=title,
        created_at=pd.Timestamp("2026-01-01"),
        updated_at=pd.Timestamp("2026-01-01"),
        message_count=0,
        model=None,
        account=parser.account,
    ))


def test_brief_prepended_to_chat(tmp_path):
    uuid = "eeee1111-2222-3333-4444-555566667777"
    nb_data = {"uuid": uuid, "title": "Brief Test", "sources": [], "guide": {}}
    chat_data = [
        {"id": "m1", "role": "user", "content": "Pergunta?", "timestamp": "2026-03-25T10:00:00Z"},
        {"id": "m2", "role": "assistant", "content": "Resposta.", "timestamp": "2026-03-25T10:01:00Z"},
    ]
    _create_notebook_dir(tmp_path, uuid, nb_data, chat_data=chat_data,
                         briefs=["# Resumo do Notebook\n\nConteudo do brief."])

    parser = NotebookLMParser(account="test")
    _add_conversation(parser, uuid)
    parser.parse_downloads(tmp_path)

    assert len(parser.messages) == 3
    brief_msg = parser.messages[0]
    assert brief_msg.sequence == 0
    assert brief_msg.role == "system"
    assert brief_msg.content_types == "brief"
    assert "Resumo do Notebook" in brief_msg.content
    assert brief_msg.message_id == f"{uuid}_brief"

    # Chat messages start at sequence 1
    assert parser.messages[1].sequence == 1
    assert parser.messages[1].role == "user"


def test_multiple_briefs_concatenated(tmp_path):
    uuid = "ffff1111-2222-3333-4444-555566667777"
    nb_data = {"uuid": uuid, "title": "Multi Brief", "sources": [], "guide": {}}
    chat_data = [
        {"id": "m1", "role": "user", "content": "Oi", "timestamp": "2026-03-25T10:00:00Z"},
    ]
    _create_notebook_dir(tmp_path, uuid, nb_data, chat_data=chat_data,
                         briefs=["Brief 1 conteudo.", "Brief 2 conteudo."])

    parser = NotebookLMParser(account="test")
    _add_conversation(parser, uuid)
    parser.parse_downloads(tmp_path)

    assert len(parser.messages) == 2  # 1 brief + 1 chat
    brief_msg = parser.messages[0]
    assert "Brief 1" in brief_msg.content
    assert "Brief 2" in brief_msg.content
    assert "---" in brief_msg.content  # separator


def test_no_brief_no_system_message(tmp_path):
    uuid = "aabb1111-2222-3333-4444-555566667777"
    nb_data = {"uuid": uuid, "title": "No Brief", "sources": [], "guide": {}}
    chat_data = [
        {"id": "m1", "role": "user", "content": "Oi", "timestamp": "2026-03-25T10:00:00Z"},
    ]
    _create_notebook_dir(tmp_path, uuid, nb_data, chat_data=chat_data)

    parser = NotebookLMParser(account="test")
    _add_conversation(parser, uuid)
    parser.parse_downloads(tmp_path)

    assert len(parser.messages) == 1
    assert parser.messages[0].role == "user"


def test_orphan_chat_skipped(tmp_path):
    """Chat sem conversa no inventario e ignorado."""
    uuid = "bbcc1111-2222-3333-4444-555566667777"
    nb_data = {"uuid": uuid, "title": "Orphan", "sources": [], "guide": {}}
    chat_data = [
        {"id": "m1", "role": "user", "content": "Oi", "timestamp": "2026-03-25T10:00:00Z"},
    ]
    _create_notebook_dir(tmp_path, uuid, nb_data, chat_data=chat_data)

    parser = NotebookLMParser(account="test")
    # Nao adiciona conversa — simula UUID nao inventariado
    parser.parse_downloads(tmp_path)

    assert len(parser.messages) == 0


def test_orphan_guides_skipped(tmp_path):
    """Guides/sources de notebook sem conversa no inventario sao ignorados."""
    uuid = "ddee1111-2222-3333-4444-555566667777"
    nb_data = {
        "uuid": uuid,
        "title": "Orphan Notebook",
        "sources": [{"uuid": "s1", "name": "doc.pdf"}],
        "guide": {"summary": "Resumo orphan."},
    }
    _create_notebook_dir(tmp_path, uuid, nb_data)

    parser = NotebookLMParser(account="test")
    # Nao adiciona conversa — UUID nao inventariado
    parser.parse_downloads(tmp_path)

    assert len(parser.guides) == 0
    assert len(parser.sources) == 0
