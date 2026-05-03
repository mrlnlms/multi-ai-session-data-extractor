"""Tests pro parser v3 do NotebookLM (Chunk 8 do plan).

Cobertura: 8 parquets canonicos+auxiliares + idempotencia + system summary.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.parsers.notebooklm import NotebookLMParser


def _build_minimal_merged():
    """Merged dict minimo pra testes — schema posicional simulado."""
    return {
        "notebooks": [
            {
                "uuid": "nb-uuid-1",
                "title": "Test Notebook",
                "account": "1",
                "create_time": 1735000000,
                "update_time": 1735100000,
                # rLM1Ne: [[title, [sources_list]]]
                "metadata": [[
                    "Test Notebook",
                    [
                        [["src-uuid-1"], "test.pdf", [None, 1000, [1735000000, 0]], [None, 2]],
                    ],
                ]],
                # VfAZjd: [[summary, [[questions]]]]
                "guide": [[
                    ["Resumo do notebook teste."],
                    [[
                        ["Pergunta 1?", "Prompt completo 1"],
                        ["Pergunta 2?", "Prompt completo 2"],
                    ]],
                    None, None, None,
                ]],
                "chat": None,
                # cFji9: [[[uuid, [uuid, content_str, ...]], ...], ts]
                "notes": [[
                    ["note-uuid-1", ["note-uuid-1", "**Briefing detalhado** sobre o tema...", []]],
                ], [1735050000, 0]],
                # gArtLc: [[[uuid, title, type, source_refs, status]]]
                "audios": [[
                    ["art-1", "Audio teste", 1, [], "ARTIFACT_STATUS_READY"],
                    ["art-2", "Blog teste", 2, [], "ARTIFACT_STATUS_READY"],
                ]],
                # hPTbtc: [[[uuid]]]
                "mind_map": [[["mm-uuid-1"]]],
                "_artifacts_individual": {
                    "art-2": {
                        "raw": [[
                            "art-2", "Blog teste", 2, [], "ARTIFACT_STATUS_READY",
                            None, None, ["# Conteudo do blog\n\nTexto..."],
                        ]],
                    }
                },
                "_mind_map_tree": {
                    "mind_map_uuid": "mm-uuid-1",
                    "raw": [[["root-node", "mm-uuid-1", [0, "tree-version"], None, ""]]],
                },
            }
        ],
        "sources": {
            "src-uuid-1": {
                "source_uuid": "src-uuid-1",
                "notebook_uuid": "nb-uuid-1",
                "raw": [
                    [
                        [["src-uuid-1"]], "test.pdf", [None, 1000], [None, 2],
                    ],
                    None, None,
                    # chunks: [[[start, end, [[[start, end, [text]]]]], ...]]
                    [[
                        [0, 30, [[[0, 30, ["Texto extraido do PDF de teste."]]]]],
                    ]],
                ],
            }
        },
    }


def test_parser_generates_9_parquets(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    expected = {
        "notebooklm_conversations.parquet",
        "notebooklm_messages.parquet",
        "notebooklm_tool_events.parquet",
        "notebooklm_branches.parquet",
        "notebooklm_sources.parquet",
        "notebooklm_notes.parquet",
        "notebooklm_outputs.parquet",
        "notebooklm_guide_questions.parquet",
        "notebooklm_source_guides.parquet",
    }
    files = {p.name for p in tmp_path.glob("*.parquet")}
    assert expected.issubset(files)


def test_source_guides_parsed_when_present(tmp_path):
    """Quando merged tem source_guides, parser popula notebooklm_source_guides.parquet."""
    merged = _build_minimal_merged()
    merged["source_guides"] = {
        "src-uuid-1": {
            "source_uuid": "src-uuid-1",
            "raw": [[
                [None,
                 ["Resumo do PDF de teste."],
                 [["TagA", "TagB"]],
                 [["Pergunta 1?", "Pergunta 2?"]]],
            ]],
        }
    }
    parser = NotebookLMParser()
    parser.parse(merged, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_source_guides.parquet")
    assert len(df) == 1
    assert df.iloc[0]["source_id"] == "src-uuid-1"
    assert "Resumo" in df.iloc[0]["summary"]
    assert "TagA" in df.iloc[0]["tags_json"]
    assert "Pergunta" in df.iloc[0]["questions_json"]


def test_conversation_per_notebook(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_conversations.parquet")
    assert len(df) == 1
    assert df.iloc[0]["conversation_id"] == "account-1_nb-uuid-1"
    assert df.iloc[0]["source"] == "notebooklm"
    assert df.iloc[0]["account"] == "1"
    assert df.iloc[0]["title"] == "Test Notebook"
    assert df.iloc[0]["model"] == "gemini"
    assert df.iloc[0]["mode"] == "chat"


def test_guide_summary_becomes_system_message(tmp_path):
    """guide.summary vira system msg sequence=0 — garante message_count >= 1."""
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_messages.parquet")
    sys_msgs = df[df["role"] == "system"]
    assert len(sys_msgs) == 1
    assert "Resumo do notebook" in sys_msgs.iloc[0]["content"]
    assert sys_msgs.iloc[0]["sequence"] == 0
    assert sys_msgs.iloc[0]["branch_id"] == "account-1_nb-uuid-1_main"


def test_conversation_summary_populated(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_conversations.parquet")
    assert df.iloc[0]["summary"] is not None
    assert "Resumo do notebook" in df.iloc[0]["summary"]


def test_branches_one_per_conv(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_branches.parquet")
    assert len(df) == 1
    assert df.iloc[0]["branch_id"] == "account-1_nb-uuid-1_main"
    assert bool(df.iloc[0]["is_active"]) is True


def test_outputs_includes_artifact_types(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_outputs.parquet")
    types = set(df["output_type"].unique())
    assert 1 in types  # audio
    assert 2 in types  # blog
    assert 10 in types  # mind_map
    blog_row = df[df["output_type"] == 2].iloc[0]
    assert blog_row["content"] is not None
    assert "Conteudo do blog" in blog_row["content"]


def test_sources_with_content(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_sources.parquet")
    assert len(df) == 1
    assert df.iloc[0]["doc_id"] == "src-uuid-1"
    assert df.iloc[0]["project_id"] == "account-1_nb-uuid-1"
    assert "Texto extraido" in df.iloc[0]["content"]
    assert df.iloc[0]["content_size"] > 0


def test_guide_questions_parsed(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_guide_questions.parquet")
    assert len(df) == 2
    assert df.iloc[0]["order"] == 0
    assert df.iloc[0]["question_text"] == "Pergunta 1?"
    assert df.iloc[1]["order"] == 1


def test_notes_parsed(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_notes.parquet")
    assert len(df) == 1
    assert df.iloc[0]["note_id"] == "note-uuid-1"
    assert "Briefing" in df.iloc[0]["content"]


def test_idempotent(tmp_path):
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    sizes_first = {p.name: p.stat().st_size for p in tmp_path.glob("*.parquet")}
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    sizes_second = {p.name: p.stat().st_size for p in tmp_path.glob("*.parquet")}
    assert sizes_first == sizes_second


def test_message_count_at_least_one(tmp_path):
    """Notebook sem chat ainda tem message_count >= 1 (guide.summary)."""
    parser = NotebookLMParser()
    parser.parse(_build_minimal_merged(), output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_conversations.parquet")
    assert df.iloc[0]["message_count"] >= 1


def test_preserved_missing_propagates(tmp_path):
    merged = _build_minimal_merged()
    merged["notebooks"][0]["_preserved_missing"] = True
    merged["notebooks"][0]["_last_seen_in_server"] = "2026-04-01"
    parser = NotebookLMParser()
    parser.parse(merged, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_conversations.parquet")
    assert bool(df.iloc[0]["is_preserved_missing"]) is True
    assert pd.notna(df.iloc[0]["last_seen_in_server"])
