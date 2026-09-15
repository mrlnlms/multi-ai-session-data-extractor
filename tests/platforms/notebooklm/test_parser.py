"""Tests pro parser v3 do NotebookLM.

Cobertura: 11 parquets canonicos+auxiliares + idempotencia + system summary.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.platforms.notebooklm.parser import NotebookLMParser


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


def test_parser_generates_11_parquets(tmp_path):
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
        "notebooklm_assets.parquet",
        "notebooklm_asset_links.parquet",
    }
    files = {p.name for p in tmp_path.glob("*.parquet")}
    assert expected.issubset(files)


def test_binary_source_pages_and_outputs_become_assets_with_exact_links(tmp_path):
    merged = _build_minimal_merged()
    account_id = "11111111-1111-4111-8111-111111111111"
    merged["notebooks"][0]["account_id"] = account_id
    account_dir = tmp_path / "data" / "merged" / "NotebookLM" / "account-1"
    source_page = account_dir / "assets" / "source_pages" / "src-uuid-1" / "page_000_x.webp"
    audio = account_dir / "assets" / "audio_overviews" / "nb-uuid-1_art-1.m4a"
    source_page.parent.mkdir(parents=True)
    audio.parent.mkdir(parents=True)
    source_page.write_bytes(b"page")
    audio.write_bytes(b"audio")
    merged["notebooks"][0]["_account_dir"] = str(account_dir)

    NotebookLMParser().parse(merged, output_dir=tmp_path / "processed")

    assets = pd.read_parquet(tmp_path / "processed" / "notebooklm_assets.parquet")
    links = pd.read_parquet(tmp_path / "processed" / "notebooklm_asset_links.parquet")
    outputs = pd.read_parquet(tmp_path / "processed" / "notebooklm_outputs.parquet")
    assert len(assets) == 2
    assert set(assets["account_id"]) == {account_id}
    assert set(links["object_type"]) == {"source", "output"}
    assert set(links["role"]) == {"context", "output"}
    assert all(not str(path).startswith(("http://", "https://")) for path in assets["asset_path"])
    assert assets["is_binary_available"].all()
    assert outputs.loc[outputs["output_id"] == "art-1", "asset_path"].iloc[0] == [
        "merged/NotebookLM/account-1/assets/audio_overviews/nb-uuid-1_art-1.m4a"
    ]
    assert '"output_id": "art-1"' in assets.loc[
        assets["asset_id"] == "art-1", "metadata_json"
    ].iloc[0]


def test_missing_binary_and_presigned_url_do_not_create_assets(tmp_path):
    merged = _build_minimal_merged()
    merged["notebooks"][0]["audios"][0][0].extend(
        [None, None, [None, None, "https://lh3.googleusercontent.com/notebooklm/signed?token=secret"]]
    )
    account_dir = tmp_path / "data" / "merged" / "NotebookLM" / "account-1"
    merged["notebooks"][0]["_account_dir"] = str(account_dir)

    NotebookLMParser().parse(merged, output_dir=tmp_path / "processed")

    assets = pd.read_parquet(tmp_path / "processed" / "notebooklm_assets.parquet")
    links = pd.read_parquet(tmp_path / "processed" / "notebooklm_asset_links.parquet")
    assert assets.empty
    assert links.empty


def test_slide_deck_files_get_deterministic_child_assets(tmp_path):
    merged = _build_minimal_merged()
    merged["notebooks"][0]["audios"][0].append(
        ["deck-1", "Deck", 8, [], "ARTIFACT_STATUS_READY"]
    )
    account_dir = tmp_path / "data" / "merged" / "NotebookLM" / "account-1"
    deck_dir = account_dir / "assets" / "slide_decks" / "nb-uuid-1_deck-1"
    deck_dir.mkdir(parents=True)
    (deck_dir / "detailed_deck.pdf").write_bytes(b"pdf")
    (deck_dir / "presenter_slides.pptx").write_bytes(b"pptx")
    merged["notebooks"][0]["_account_dir"] = str(account_dir)

    parser = NotebookLMParser()
    parser.parse(merged, output_dir=tmp_path / "first")
    parser.parse(merged, output_dir=tmp_path / "second")
    first = pd.read_parquet(tmp_path / "first" / "notebooklm_assets.parquet")
    second = pd.read_parquet(tmp_path / "second" / "notebooklm_assets.parquet")
    first = first[first["metadata_json"].str.contains('"output_id": "deck-1"')]
    second = second[second["metadata_json"].str.contains('"output_id": "deck-1"')]
    assert len(first) == 2
    assert first["asset_id"].tolist() == second["asset_id"].tolist()
    assert "deck-1" not in set(first["asset_id"])


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


def test_account_label_does_not_change_notebook_conversation_id(tmp_path):
    merged = _build_minimal_merged()
    merged["notebooks"][0]["account"] = "name@example.com"
    merged["notebooks"][0]["account_key"] = "1"

    NotebookLMParser().parse(merged, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_conversations.parquet")

    assert df.iloc[0]["conversation_id"] == "account-1_nb-uuid-1"
    assert df.iloc[0]["account"] == "name@example.com"


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


def test_duplicate_artifact_rows_are_not_emitted(tmp_path):
    merged = _build_minimal_merged()
    merged["notebooks"][0]["audios"][0].append(
        ["art-1", "Audio teste", 1, [], "ARTIFACT_STATUS_READY"]
    )

    NotebookLMParser().parse(merged, output_dir=tmp_path)
    df = pd.read_parquet(tmp_path / "notebooklm_outputs.parquet")

    assert len(df[df["output_id"] == "art-1"]) == 1


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
