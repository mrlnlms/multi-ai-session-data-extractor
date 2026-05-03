# tests/schema/test_models.py
import pytest
import pandas as pd
from src.schema.models import (
    Conversation,
    Message,
    ToolEvent,
    ConversationProject,
    conversations_to_df,
    messages_to_df,
    tool_events_to_df,
    conversation_projects_to_df,
    VALID_MODES,
)


def test_conversation_to_dict():
    conv = Conversation(
        conversation_id="claude_abc123",
        source="claude_ai",
        title="Test chat",
        created_at=pd.Timestamp("2026-01-01 10:00:00"),
        updated_at=pd.Timestamp("2026-01-01 11:00:00"),
        message_count=5,
        model="claude-sonnet-4-6",
    )
    d = conv.to_dict()
    assert d["conversation_id"] == "claude_abc123"
    assert d["source"] == "claude_ai"
    assert d["message_count"] == 5


def test_message_to_dict():
    msg = Message(
        message_id="msg_001",
        conversation_id="claude_abc123",
        source="claude_ai",
        sequence=1,
        role="user",
        content="Hello",
        model=None,
        created_at=pd.Timestamp("2026-01-01 10:00:00"),
    )
    d = msg.to_dict()
    assert d["sequence"] == 1
    assert d["role"] == "user"
    assert d["model"] is None


def test_tool_event_to_dict():
    event = ToolEvent(
        event_id="evt_1",
        conversation_id="conv_1",
        message_id="msg_1",
        source="claude_code",
        event_type="bash_command",
        tool_name="Bash",
        command="git status",
        success=True,
    )
    d = event.to_dict()
    assert d["event_type"] == "bash_command"
    assert d["source"] == "claude_code"
    assert d["command"] == "git status"


def test_conversation_project_to_dict():
    proj = ConversationProject(
        conversation_id="claude_1",
        project_tag="mirror-notes",
        tagged_by="manual",
    )
    d = proj.to_dict()
    assert d["project_tag"] == "mirror-notes"
    assert d["confidence"] is None


def test_conversations_to_df():
    convs = [
        Conversation(
            conversation_id="claude_1",
            source="claude_ai",
            title="Chat 1",
            created_at=pd.Timestamp("2026-01-01"),
            updated_at=pd.Timestamp("2026-01-01"),
            message_count=3,
            model="claude-sonnet-4-6",
        ),
        Conversation(
            conversation_id="gpt_1",
            source="chatgpt",
            title="Chat 2",
            created_at=pd.Timestamp("2026-01-02"),
            updated_at=pd.Timestamp("2026-01-02"),
            message_count=7,
            model="gpt-4o",
        ),
    ]
    df = conversations_to_df(convs)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == [
        "conversation_id", "source", "title",
        "created_at", "updated_at", "message_count", "model", "account", "mode", "project", "url",
        "interaction_type", "parent_session_id",
        "project_id", "gizmo_id", "gizmo_name", "gizmo_resolved",
        "is_preserved_missing", "last_seen_in_server", "is_pinned",
        "is_archived", "is_temporary",
        "summary", "settings_json",
        "capture_method",
    ]


def test_messages_to_df():
    msgs = [
        Message(
            message_id="msg_1",
            conversation_id="claude_1",
            source="claude_ai",
            sequence=1,
            role="user",
            content="Oi",
            model=None,
            created_at=pd.Timestamp("2026-01-01 10:00:00"),
        ),
        Message(
            message_id="msg_2",
            conversation_id="claude_1",
            source="claude_ai",
            sequence=2,
            role="assistant",
            content="Ola!",
            model="claude-sonnet-4-6",
            created_at=pd.Timestamp("2026-01-01 10:00:01"),
        ),
    ]
    df = messages_to_df(msgs)
    assert len(df) == 2
    assert df["sequence"].tolist() == [1, 2]


def test_tool_events_to_df():
    events = [
        ToolEvent(
            event_id="evt_1",
            conversation_id="conv_1",
            message_id="msg_1",
            source="claude_code",
            event_type="file_edit",
            tool_name="Edit",
            file_path="src/main.py",
        ),
    ]
    df = tool_events_to_df(events)
    assert len(df) == 1
    assert "event_type" in df.columns


def test_conversation_projects_to_df():
    projects = [
        ConversationProject(
            conversation_id="claude_1",
            project_tag="qda",
            tagged_by="nlp_suggested",
            confidence=0.85,
        ),
    ]
    df = conversation_projects_to_df(projects)
    assert len(df) == 1
    assert df.iloc[0]["confidence"] == 0.85


def test_message_with_attachments():
    """attachment_names armazena JSON array de nomes de arquivo."""
    import json
    files = ["relatorio.pdf", "screenshot.png"]
    msg = Message(
        message_id="msg_1",
        conversation_id="deepseek_1",
        source="deepseek",
        sequence=1,
        role="user",
        content="Analise este arquivo",
        model="deepseek-chat",
        created_at=pd.Timestamp("2025-01-29"),
        attachment_names=json.dumps(files),
    )
    d = msg.to_dict()
    parsed = json.loads(d["attachment_names"])
    assert parsed == ["relatorio.pdf", "screenshot.png"]


def test_message_without_attachments():
    msg = Message(
        message_id="msg_1",
        conversation_id="claude_1",
        source="claude_ai",
        sequence=1,
        role="user",
        content="Hello",
        model=None,
        created_at=pd.Timestamp("2026-01-01"),
    )
    assert msg.attachment_names is None


def test_deepseek_is_valid_source():
    conv = Conversation(
        conversation_id="deepseek_1",
        source="deepseek",
        title="Test",
        created_at=pd.Timestamp("2025-01-29"),
        updated_at=pd.Timestamp("2025-01-29"),
        message_count=2,
        model="deepseek-chat",
    )
    assert conv.source == "deepseek"


def test_invalid_source_raises():
    """source invalido deve levantar ValueError."""
    with pytest.raises(ValueError, match="source"):
        Conversation(
            conversation_id="test_1",
            source="invalid_source",
            title=None,
            created_at=pd.Timestamp("2026-01-01"),
            updated_at=pd.Timestamp("2026-01-01"),
            message_count=0,
            model=None,
        )


def test_invalid_role_raises():
    """role invalido deve levantar ValueError."""
    with pytest.raises(ValueError, match="role"):
        Message(
            message_id="msg_1",
            conversation_id="test_1",
            source="claude_ai",
            sequence=1,
            role="invalid_role",
            content="Hello",
            model=None,
            created_at=pd.Timestamp("2026-01-01"),
        )


def test_conversation_with_mode():
    conv = Conversation(
        conversation_id="ds_1",
        source="deepseek",
        title="Test",
        created_at=pd.Timestamp("2025-01-29"),
        updated_at=pd.Timestamp("2025-01-29"),
        message_count=2,
        model="deepseek-chat",
        mode="search",
    )
    assert conv.mode == "search"


def test_conversation_invalid_mode_raises():
    with pytest.raises(ValueError, match="mode"):
        Conversation(
            conversation_id="ds_1",
            source="deepseek",
            title="Test",
            created_at=pd.Timestamp("2025-01-29"),
            updated_at=pd.Timestamp("2025-01-29"),
            message_count=2,
            model="deepseek-chat",
            mode="invalid_mode",
        )


def test_conversation_mode_none_is_valid():
    conv = Conversation(
        conversation_id="ds_1",
        source="deepseek",
        title="Test",
        created_at=pd.Timestamp("2025-01-29"),
        updated_at=pd.Timestamp("2025-01-29"),
        message_count=2,
        model="deepseek-chat",
    )
    assert conv.mode is None


def test_message_with_thinking():
    msg = Message(
        message_id="msg_1",
        conversation_id="ds_1",
        source="deepseek",
        sequence=1,
        role="assistant",
        content="Voce pode usar...",
        model="deepseek-chat",
        created_at=pd.Timestamp("2025-03-15"),
        thinking="O usuario quer saber sobre X...",
    )
    assert msg.thinking == "O usuario quer saber sobre X..."
    assert msg.tool_results is None
    assert msg.content_types is None


def test_message_with_tool_results():
    import json
    tool_json = json.dumps({"type": "SEARCH", "results": [{"url": "https://example.com"}]})
    msg = Message(
        message_id="msg_1",
        conversation_id="ds_1",
        source="deepseek",
        sequence=1,
        role="assistant",
        content="Encontrei estudos...",
        model="deepseek-chat",
        created_at=pd.Timestamp("2025-03-15"),
        tool_results=tool_json,
    )
    parsed = json.loads(msg.tool_results)
    assert parsed["type"] == "SEARCH"


def test_message_with_content_types():
    msg = Message(
        message_id="msg_1",
        conversation_id="claude_1",
        source="claude_ai",
        sequence=1,
        role="user",
        content="Analisa esse CSV",
        model=None,
        created_at=pd.Timestamp("2025-06-20"),
        content_types="text,document",
    )
    assert msg.content_types == "text,document"


def test_conversation_mode_cli():
    conv = Conversation(
        conversation_id="cli_1",
        source="codex",
        title="Session",
        created_at=pd.Timestamp("2026-01-01"),
        updated_at=pd.Timestamp("2026-01-01"),
        message_count=5,
        model="gpt-5.2-codex",
        mode="cli",
    )
    assert conv.mode == "cli"


def test_conversation_interaction_type_default():
    conv = Conversation(
        conversation_id="test_1", source="chatgpt", title="Test",
        created_at=pd.Timestamp("2026-01-01"), updated_at=pd.Timestamp("2026-01-01"),
        message_count=1, model=None,
    )
    assert conv.interaction_type == "human_ai"
    assert conv.parent_session_id is None


def test_conversation_interaction_type_ai_ai():
    conv = Conversation(
        conversation_id="agent-abc123", source="claude_code", title=None,
        created_at=pd.Timestamp("2026-01-01"), updated_at=pd.Timestamp("2026-01-01"),
        message_count=42, model="claude-opus-4-6", mode="cli",
        interaction_type="ai_ai", parent_session_id="session-001",
    )
    assert conv.interaction_type == "ai_ai"
    assert conv.parent_session_id == "session-001"


def test_conversation_invalid_interaction_type_raises():
    with pytest.raises(ValueError, match="interaction_type"):
        Conversation(
            conversation_id="test_1", source="chatgpt", title="Test",
            created_at=pd.Timestamp("2026-01-01"), updated_at=pd.Timestamp("2026-01-01"),
            message_count=1, model=None, interaction_type="invalid",
        )


def test_chatgpt_is_valid_source():
    conv = Conversation(
        conversation_id="gpt_1", source="chatgpt", title="Test",
        created_at=pd.Timestamp("2026-04-28"), updated_at=pd.Timestamp("2026-04-28"),
        message_count=2, model="gpt-5",
    )
    assert conv.source == "chatgpt"


def test_conversation_v3_fields_defaults():
    conv = Conversation(
        conversation_id="gpt_1", source="chatgpt", title=None,
        created_at=pd.Timestamp("2026-04-28"), updated_at=pd.Timestamp("2026-04-28"),
        message_count=0, model=None,
    )
    assert conv.project_id is None
    assert conv.gizmo_id is None
    assert conv.gizmo_name is None
    assert conv.gizmo_resolved is True
    assert conv.is_preserved_missing is False
    assert conv.last_seen_in_server is None


def test_conversation_v3_fields_set():
    conv = Conversation(
        conversation_id="gpt_1", source="chatgpt", title="Test",
        created_at=pd.Timestamp("2026-04-28"), updated_at=pd.Timestamp("2026-04-28"),
        message_count=2, model="gpt-5",
        project_id="g-p-abc", gizmo_id="g-xyz", gizmo_name="My Custom GPT",
        gizmo_resolved=False, is_preserved_missing=True,
        last_seen_in_server=pd.Timestamp("2026-04-20"),
    )
    assert conv.project_id == "g-p-abc"
    assert conv.gizmo_id == "g-xyz"
    assert conv.gizmo_resolved is False
    assert conv.is_preserved_missing is True


def test_message_branch_id_default_is_conv_main():
    msg = Message(
        message_id="msg_1", conversation_id="conv-abc", source="chatgpt",
        sequence=1, role="user", content="oi", model=None,
        created_at=pd.Timestamp("2026-04-28"),
    )
    assert msg.branch_id == "conv-abc_main"


def test_message_branch_id_explicit_is_respected():
    msg = Message(
        message_id="msg_1", conversation_id="conv-abc", source="chatgpt",
        sequence=1, role="user", content="oi", model=None,
        created_at=pd.Timestamp("2026-04-28"),
        branch_id="conv-abc_fork-xyz",
    )
    assert msg.branch_id == "conv-abc_fork-xyz"


def test_message_v3_fields():
    msg = Message(
        message_id="msg_1", conversation_id="conv-abc", source="chatgpt",
        sequence=1, role="assistant", content="[imagem gerada]", model="gpt-5",
        created_at=pd.Timestamp("2026-04-28"),
        asset_paths=["data/raw/ChatGPT/assets/images/conv/file_abc.png"],
        finish_reason="stop", is_voice=False, voice_direction=None,
    )
    assert msg.asset_paths == ["data/raw/ChatGPT/assets/images/conv/file_abc.png"]
    assert msg.finish_reason == "stop"
    assert msg.is_hidden is False
    assert msg.hidden_reason is None


def test_message_voice_direction():
    msg = Message(
        message_id="msg_1", conversation_id="conv-abc", source="chatgpt",
        sequence=1, role="user", content="ola", model=None,
        created_at=pd.Timestamp("2026-04-28"),
        is_voice=True, voice_direction="in",
    )
    assert msg.is_voice is True
    assert msg.voice_direction == "in"


def test_tool_event_with_result():
    evt = ToolEvent(
        event_id="evt_1", conversation_id="conv_1", message_id="msg_1",
        source="chatgpt", event_type="search", tool_name="browser.search",
        result="[\"snippet 1\", \"snippet 2\"]",
    )
    assert evt.result == "[\"snippet 1\", \"snippet 2\"]"


def test_branch_to_dict():
    from src.schema.models import Branch
    b = Branch(
        branch_id="conv-abc_main", conversation_id="conv-abc",
        source="chatgpt", root_message_id="root", leaf_message_id="leaf",
        is_active=True, created_at=pd.Timestamp("2026-04-28"),
        parent_branch_id=None,
    )
    d = b.to_dict()
    assert d["branch_id"] == "conv-abc_main"
    assert d["is_active"] is True
    assert d["parent_branch_id"] is None


def test_branches_to_df():
    from src.schema.models import Branch, branches_to_df
    branches = [
        Branch(branch_id="c1_main", conversation_id="c1", source="chatgpt",
               root_message_id="r1", leaf_message_id="l1", is_active=False,
               created_at=pd.Timestamp("2026-04-28"), parent_branch_id=None),
        Branch(branch_id="c1_fork", conversation_id="c1", source="chatgpt",
               root_message_id="r2", leaf_message_id="l2", is_active=True,
               created_at=pd.Timestamp("2026-04-28"), parent_branch_id="c1_main"),
    ]
    df = branches_to_df(branches)
    assert len(df) == 2
    assert "branch_id" in df.columns
    assert "parent_branch_id" in df.columns


def test_branch_invalid_source_raises():
    from src.schema.models import Branch
    with pytest.raises(ValueError, match="source"):
        Branch(
            branch_id="b1", conversation_id="c1", source="invalid_xx",
            root_message_id="r", leaf_message_id="l", is_active=False,
            created_at=pd.Timestamp("2026-04-28"),
        )
