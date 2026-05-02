"""Tests pra dataclasses NotebookLM-specific (Chunk 7 do plan)."""

import pandas as pd
import pytest

from src.schema.models import (
    NotebookLMNote, notebooklm_notes_to_df,
    NotebookLMOutput, notebooklm_outputs_to_df,
    NotebookLMGuideQuestion, notebooklm_guide_questions_to_df,
    VALID_OUTPUT_TYPES,
)


def test_notebooklm_note_validates_source():
    with pytest.raises(ValueError, match="source"):
        NotebookLMNote(
            note_id="n1", conversation_id="c1", source="invalid",
            account="1", title="t", content="x", kind="note",
            source_refs_json=None, created_at=None,
        )


def test_notebooklm_note_validates_kind():
    with pytest.raises(ValueError, match="kind"):
        NotebookLMNote(
            note_id="n1", conversation_id="c1", source="notebooklm",
            account="1", title="t", content="x", kind="invalid",
            source_refs_json=None, created_at=None,
        )


def test_notebooklm_note_valid():
    n = NotebookLMNote(
        note_id="n1", conversation_id="account-1_nb1", source="notebooklm",
        account="1", title="Title", content="content", kind="brief",
        source_refs_json='["src1"]', created_at=pd.Timestamp("2026-05-02"),
    )
    assert n.kind == "brief"


def test_notebooklm_output_validates_type():
    with pytest.raises(ValueError, match="output_type"):
        NotebookLMOutput(
            output_id="o1", conversation_id="c1", source="notebooklm",
            account="1", output_type=99, output_type_name="invalid",
            title="t", status=None, asset_path=None, content=None,
            source_refs_json=None, created_at=None,
        )


def test_notebooklm_output_validates_type_name_match():
    # type=1 esperado output_type_name='audio_overview'
    with pytest.raises(ValueError, match="output_type_name"):
        NotebookLMOutput(
            output_id="o1", conversation_id="c1", source="notebooklm",
            account="1", output_type=1, output_type_name="wrong_name",
            title="t", status=None, asset_path=None, content=None,
            source_refs_json=None, created_at=None,
        )


def test_notebooklm_output_all_valid_types():
    """Cobre todos os 8 tipos validos (1, 2, 3, 4, 7, 8, 9, 10)."""
    for t, name in VALID_OUTPUT_TYPES.items():
        o = NotebookLMOutput(
            output_id=f"o{t}", conversation_id="c1", source="notebooklm",
            account="1", output_type=t, output_type_name=name,
            title=None, status=None, asset_path=None, content=None,
            source_refs_json=None, created_at=None,
        )
        assert o.output_type == t
        assert o.output_type_name == name


def test_notes_to_df_empty():
    df = notebooklm_notes_to_df([])
    assert isinstance(df, pd.DataFrame)
    assert "note_id" in df.columns


def test_outputs_to_df_with_rows():
    o = NotebookLMOutput(
        output_id="o1", conversation_id="account-1_nb1", source="notebooklm",
        account="1", output_type=1, output_type_name="audio_overview",
        title="audio teste", status="ARTIFACT_STATUS_READY",
        asset_path=["data/assets/audio.mp4"], content=None,
        source_refs_json='["src1","src2"]', created_at=pd.Timestamp("2026-05-02"),
    )
    df = notebooklm_outputs_to_df([o])
    assert len(df) == 1
    assert df.iloc[0]["output_type"] == 1
    assert df.iloc[0]["asset_path"] == ["data/assets/audio.mp4"]


def test_guide_question_basic():
    q = NotebookLMGuideQuestion(
        question_id="q1", conversation_id="c1", source="notebooklm",
        account="1", question_text="Qual...?", full_prompt="Create a briefing...",
        order=0,
    )
    df = notebooklm_guide_questions_to_df([q])
    assert len(df) == 1
    assert df.iloc[0]["order"] == 0


def test_guide_question_validates_source():
    with pytest.raises(ValueError, match="source"):
        NotebookLMGuideQuestion(
            question_id="q1", conversation_id="c1", source="invalid",
            account="1", question_text="?", full_prompt="?", order=0,
        )
