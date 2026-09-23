import pandas as pd
import pytest
from dataclasses import fields

from src.schema.models import (
    AgentMemory,
    AgentMemoryTemporalEvidence,
    AgentMemoryVersion,
    VALID_MEMORY_KINDS,
    agent_memories_to_df,
    agent_memory_temporal_evidence_to_df,
    agent_memory_versions_to_df,
)


def test_agent_memory_minimal_construction():
    m = AgentMemory(
        memory_id="claude_code:proj:user_profile.md",
        source="claude_code",
        project_path="/Users/x/proj",
        project_key="-Users-x-proj",
        file_name="user_profile.md",
        name="User profile",
        description="Senior researcher",
        kind="user",
        content="---\nname: User profile\n---\nbody",
        content_size=40,
        created_at=pd.Timestamp("2026-05-01"),
        updated_at=pd.Timestamp("2026-05-07"),
    )
    assert m.kind == "user"
    assert m.is_preserved_missing is False


def test_agent_memory_invalid_source_raises():
    with pytest.raises(ValueError, match="source"):
        AgentMemory(
            memory_id="x",
            source="invalid_source",
            project_path=None,
            project_key=None,
            file_name="x.md",
            name=None, description=None,
            kind="other",
            content="", content_size=0,
            created_at=pd.NaT, updated_at=pd.NaT,
        )


def test_agent_memory_invalid_kind_raises():
    with pytest.raises(ValueError, match="kind"):
        AgentMemory(
            memory_id="x",
            source="claude_code",
            project_path=None, project_key=None,
            file_name="x.md",
            name=None, description=None,
            kind="bogus",
            content="", content_size=0,
            created_at=pd.NaT, updated_at=pd.NaT,
        )


def test_codex_memory_allows_null_project():
    m = AgentMemory(
        memory_id="codex::global.md",
        source="codex",
        project_path=None, project_key=None,
        file_name="global.md",
        name=None, description=None,
        kind="other",
        content="", content_size=0,
        created_at=pd.NaT, updated_at=pd.NaT,
    )
    assert m.project_path is None


def test_agent_memories_to_df_empty():
    df = agent_memories_to_df([])
    assert "memory_id" in df.columns
    assert "kind" in df.columns
    assert len(df) == 0


def test_agent_memory_auxiliary_empty_frames_keep_schema():
    assert list(agent_memory_versions_to_df([]).columns) == [
        f.name for f in fields(AgentMemoryVersion)
    ]
    assert list(agent_memory_temporal_evidence_to_df([]).columns) == [
        f.name for f in fields(AgentMemoryTemporalEvidence)
    ]


def test_agent_memory_version_rejects_invalid_confidence():
    with pytest.raises(ValueError, match="confidence"):
        AgentMemoryVersion(
            version_id="m:abc", memory_id="m", source="codex",
            relative_path="memories/a.md", content_sha256="abc", content="x",
            content_size=1, source_modified_at=None, source_birth_at=None,
            first_seen_at=None, last_seen_at=None, captured_at=None,
            effective_created_at=None, effective_updated_at=None,
            created_at_basis=None, updated_at_basis=None,
            created_at_confidence="certain",
        )


def test_agent_memory_temporal_evidence_rejects_invalid_confidence():
    with pytest.raises(ValueError, match="confidence"):
        AgentMemoryTemporalEvidence(
            evidence_id="e", memory_id="m", version_id="v", source="codex",
            evidence_type="first_observed", timestamp=None, confidence="certain",
            locator=None, details_json=None, is_inference=False,
        )


def test_agent_memories_to_df_roundtrip():
    items = [AgentMemory(
        memory_id=f"claude_code:p:{i}.md",
        source="claude_code",
        project_path="/p", project_key="-p",
        file_name=f"{i}.md",
        name=None, description=None,
        kind="other",
        content="x", content_size=1,
        created_at=pd.NaT, updated_at=pd.NaT,
    ) for i in range(3)]
    df = agent_memories_to_df(items)
    assert len(df) == 3
    assert set(df["memory_id"]) == {f"claude_code:p:{i}.md" for i in range(3)}


def test_all_valid_memory_kinds_accepted():
    """Smoke test cobrindo todos os kinds validos."""
    for kind in VALID_MEMORY_KINDS:
        m = AgentMemory(
            memory_id=f"claude_code:p:{kind}.md",
            source="claude_code",
            project_path="/p", project_key="-p",
            file_name=f"{kind}.md",
            name=None, description=None,
            kind=kind,
            content="x", content_size=1,
            created_at=pd.NaT, updated_at=pd.NaT,
        )
        assert m.kind == kind
