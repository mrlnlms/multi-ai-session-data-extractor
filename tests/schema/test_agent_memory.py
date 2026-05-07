import pandas as pd
import pytest
from src.schema.models import AgentMemory, VALID_MEMORY_KINDS, agent_memories_to_df


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
