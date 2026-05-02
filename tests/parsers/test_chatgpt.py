"""Testes do parser v3 do ChatGPT.

Cada feature tem fixture em tests/extractors/chatgpt/fixtures/raw_with_*.json.
Usamos um helper pra "wrap" a fixture (formato {conversation_id, conversation})
no shape de merged ({conversations: {<id>: <conv>}}) que o parser consome.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.parsers.chatgpt import ChatGPTParser


FIXTURES_DIR = Path(__file__).parent.parent / "extractors" / "chatgpt" / "fixtures"


def _make_merged(fixture_name: str, tmp_path: Path) -> Path:
    """Carrega fixture e escreve em formato de merged em tmp_path."""
    with open(FIXTURES_DIR / fixture_name, encoding="utf-8") as f:
        wrapper = json.load(f)
    conv_id = wrapper["conversation_id"]
    conv = wrapper["conversation"]
    merged = {"conversations": {conv_id: conv}}
    out = tmp_path / "chatgpt_merged.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    return out


def _parse(fixture_name: str, tmp_path: Path, raw_root: Path | None = None) -> ChatGPTParser:
    merged = _make_merged(fixture_name, tmp_path)
    parser = ChatGPTParser(raw_root=raw_root or tmp_path)
    parser.parse(merged)
    return parser


# ============================================================
# voice
# ============================================================

def test_parse_voice_extracts_transcript_and_direction(tmp_path):
    parser = _parse("raw_with_voice.json", tmp_path)
    assert parser.conversations, "deve gerar pelo menos 1 conv"
    voice_msgs = [m for m in parser.messages if m.is_voice]
    assert voice_msgs, "fixture voice deve produzir >=1 msg com is_voice=True"
    # Direction: in (user) ou out (assistant)
    assert any(m.voice_direction in ("in", "out") for m in voice_msgs)
    # content_types deve marcar audio_transcription
    assert any("audio_transcription" in (m.content_types or "") for m in voice_msgs)


# ============================================================
# DALL-E (achado empirico: aparece em role=tool, vira ToolEvent)
# ============================================================

def test_parse_dalle_creates_image_generation_event(tmp_path):
    parser = _parse("raw_with_dalle.json", tmp_path)
    # DALL-E aparece sempre em role=tool no merged real, vira ToolEvent
    img_events = [e for e in parser.events if e.event_type == "image_generation"]
    assert img_events, "fixture dalle deve gerar tool_events com event_type='image_generation'"


def test_parse_dalle_resolves_file_path_when_file_present(tmp_path):
    """Quando o file existe em <raw_root>/assets/images/<conv>/<file_id>__*,
    o ToolEvent (role=tool com DALL-E) preenche file_path."""
    with open(FIXTURES_DIR / "raw_with_dalle.json", encoding="utf-8") as f:
        wrapper = json.load(f)
    conv_id = wrapper["conversation_id"]
    conv = wrapper["conversation"]

    pointer = None
    for n in conv.get("mapping", {}).values():
        msg = (n.get("message") or {})
        for p in (msg.get("content") or {}).get("parts") or []:
            if isinstance(p, dict) and p.get("content_type") == "image_asset_pointer":
                if (p.get("metadata") or {}).get("dalle"):
                    pointer = p.get("asset_pointer")
                    break
        if pointer:
            break
    assert pointer, "fixture deve ter pointer DALL-E"

    file_id = pointer.split("://", 1)[1]
    fake_assets = tmp_path / "assets" / "images" / conv_id
    fake_assets.mkdir(parents=True, exist_ok=True)
    (fake_assets / f"{file_id}__test.png").write_bytes(b"fake-png")

    merged = tmp_path / "chatgpt_merged.json"
    merged.write_text(json.dumps({"conversations": {conv_id: conv}}, ensure_ascii=False))

    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(merged)

    img_events = [e for e in parser.events if e.event_type == "image_generation"]
    assert img_events
    paths = [e.file_path for e in img_events if e.file_path]
    assert paths, "ToolEvent DALL-E deve ter file_path populado"
    assert any(file_id in p for p in paths)


def test_parse_user_image_upload_populates_asset_paths_in_message(tmp_path):
    """Uploads de imagem (image_asset_pointer SEM dalle) em role=user viram
    Message com asset_paths populado."""
    fake_conv = {
        "id": "upload-1", "title": "test",
        "create_time": 1700000000, "update_time": 1700000100,
        "current_node": "msg-user",
        "mapping": {
            "root": {"id": "root", "parent": None, "children": ["msg-user"], "message": None},
            "msg-user": {
                "id": "msg-user", "parent": "root", "children": [],
                "message": {
                    "id": "msg-user", "create_time": 1700000050,
                    "author": {"role": "user"},
                    "content": {
                        "content_type": "multimodal_text",
                        "parts": [
                            {"content_type": "image_asset_pointer",
                             "asset_pointer": "file-service://file-ABCDEF",
                             "metadata": {}},
                            "analise essa imagem"
                        ],
                    },
                    "metadata": {},
                },
            },
        },
    }
    # Cria asset no disco
    fake_assets = tmp_path / "assets" / "images" / "upload-1"
    fake_assets.mkdir(parents=True, exist_ok=True)
    (fake_assets / "file-ABCDEF__photo.png").write_bytes(b"fake")

    merged = tmp_path / "chatgpt_merged.json"
    merged.write_text(json.dumps({"conversations": {"upload-1": fake_conv}}))

    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(merged)

    user_msgs = [m for m in parser.messages if m.role == "user"]
    assert user_msgs
    msg = user_msgs[0]
    assert msg.asset_paths is not None
    assert any("file-ABCDEF" in p for p in msg.asset_paths)
    assert "image_upload" in (msg.content_types or "")


# ============================================================
# Canvas
# ============================================================

def test_parse_canvas_creates_tool_events(tmp_path):
    parser = _parse("raw_with_canvas.json", tmp_path)
    canvas_events = [e for e in parser.events if e.event_type == "canvas"]
    assert canvas_events, "fixture canvas deve gerar tool_events com event_type='canvas'"
    # tool_name deve preservar canmore.* quando aplicavel
    assert any((e.tool_name or "").startswith("canmore.") or e.tool_name == "canmore"
               for e in canvas_events)


# ============================================================
# Deep Research
# ============================================================

def test_parse_deep_research_creates_tool_events(tmp_path):
    parser = _parse("raw_with_deep_research.json", tmp_path)
    dr_events = [e for e in parser.events if e.event_type == "deep_research"]
    assert dr_events, "fixture deep_research deve gerar tool_events com event_type='deep_research'"


# ============================================================
# Tether quote
# ============================================================

def test_parse_tether_quote_creates_tool_event_not_message(tmp_path):
    parser = _parse("raw_with_tether_quote.json", tmp_path)
    tether_events = [e for e in parser.events if e.event_type == "quote"]
    assert tether_events, "fixture tether_quote deve gerar event_type='quote'"
    assert all(e.tool_name == "tether_quote" for e in tether_events)
    # Tether_quote NAO deve aparecer como Message — content_type tether_quote
    # nao deve estar na CSV de content_types das messages
    tether_msg = [m for m in parser.messages if "tether_quote" in (m.content_types or "")]
    assert not tether_msg, "tether_quote nao deve virar Message regular"


# ============================================================
# Custom GPT vs Project
# ============================================================

def test_parse_custom_gpt_distinguishes_from_project(tmp_path):
    parser = _parse("raw_with_custom_gpt.json", tmp_path)
    assert parser.conversations
    conv = parser.conversations[0]
    # A fixture tem gizmo_id g-* (Custom GPT real, nao g-p-*)
    assert conv.gizmo_id is not None
    assert conv.gizmo_id.startswith("g-")
    assert not conv.gizmo_id.startswith("g-p-"), (
        f"gizmo_id de Custom GPT real nao deve comecar com 'g-p-': {conv.gizmo_id!r}"
    )


def test_parse_project_id_separates_from_gizmo_id(tmp_path):
    """Conv com gizmo_id g-p-* (Project) deve ter project_id setado e gizmo_id None."""
    # Sintetizar uma conv com g-p-* gizmo_id
    fake_conv = {
        "id": "fake-1",
        "title": "test",
        "create_time": 1700000000,
        "update_time": 1700000100,
        "gizmo_id": "g-p-fake-project-id",
        "current_node": "root",
        "mapping": {
            "root": {
                "id": "root", "parent": None, "children": [],
                "message": {
                    "id": "root", "create_time": 1700000000,
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["oi"]},
                    "metadata": {},
                },
            }
        },
    }
    merged = tmp_path / "chatgpt_merged.json"
    merged.write_text(json.dumps({"conversations": {"fake-1": fake_conv}}))
    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(merged)
    assert parser.conversations
    c = parser.conversations[0]
    assert c.project_id == "g-p-fake-project-id"
    assert c.gizmo_id is None


# ============================================================
# Tools (role=tool)
# ============================================================

def test_parse_tools_creates_events_with_correct_event_type(tmp_path):
    parser = _parse("raw_with_tools.json", tmp_path)
    assert parser.events, "fixture tools deve gerar >=1 ToolEvent"
    # Cada ToolEvent deve ter event_type classificado
    types = {e.event_type for e in parser.events}
    assert types, "events devem ter event_type"
    # role=tool messages NAO devem aparecer como Messages
    assert not any(m.role == "tool" for m in parser.messages)


def test_parse_computer_use_creates_computer_use_events(tmp_path):
    """ChatGPT Agent / Computer Use: tools com author.name começando em
    computer.* ou container.* viram ToolEvents com event_type='computer_use'.
    Tool name preservado exato (computer.get, container.exec, etc)."""
    parser = _parse("raw_with_computer_use.json", tmp_path)
    compute_events = [
        e for e in parser.events if e.event_type == "computer_use"
    ]
    assert compute_events, (
        "fixture computer_use deve gerar >=1 ToolEvent com event_type='computer_use'"
    )
    # Tool names devem ser preservados (não redactados — agente real)
    tool_names = {e.tool_name for e in compute_events}
    assert all(
        n and n.startswith(("computer.", "container.")) for n in tool_names
    ), f"tool_names devem começar com computer./container.: {tool_names}"
    # Cada compute event deve estar linkado à conversation_id da fixture
    conv_ids = {e.conversation_id for e in compute_events}
    assert len(conv_ids) == 1, f"todos events da mesma conv: {conv_ids}"


# ============================================================
# Branch default + idempotencia + smoke
# ============================================================

def test_parse_main_branch_id_is_default(tmp_path):
    parser = _parse("raw_with_voice.json", tmp_path)
    assert parser.conversations
    conv_id = parser.conversations[0].conversation_id
    expected = f"{conv_id}_main"
    assert all(m.branch_id == expected for m in parser.messages)


def test_parse_idempotent_two_runs_produce_same_output(tmp_path):
    merged = _make_merged("raw_with_tools.json", tmp_path)
    p1 = ChatGPTParser(raw_root=tmp_path)
    p1.parse(merged)
    p2 = ChatGPTParser(raw_root=tmp_path)
    p2.parse(merged)
    assert [c.to_dict() for c in p1.conversations] == [c.to_dict() for c in p2.conversations]
    assert [m.to_dict() for m in p1.messages] == [m.to_dict() for m in p2.messages]
    assert [e.to_dict() for e in p1.events] == [e.to_dict() for e in p2.events]


def test_parse_is_pinned_propagates_from_is_starred(tmp_path):
    """ChatGPT marca conv pinada via is_starred + pinned_time. Parser
    canonico mapeia is_starred -> Conversation.is_pinned (uniformiza com
    Perplexity). Validado empiricamente via probe Chrome MCP 2026-05-01."""
    def _conv(cid, **extra):
        c = {
            "id": cid, "title": cid,
            "create_time": "2025-01-01T00:00:00Z",
            "update_time": "2025-01-01T00:01:00Z",
            "current_node": "msg1",
            "mapping": {
                "root": {"id": "root", "children": ["msg1"], "parent": None},
                "msg1": {
                    "id": "msg1", "parent": "root", "children": [],
                    "message": {
                        "id": "msg1",
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["hi"]},
                        "create_time": 1735689600,
                        "status": "finished_successfully",
                        "metadata": {},
                    },
                },
            },
        }
        c.update(extra)
        return c

    merged = {"conversations": {
        "conv-pinned": _conv("conv-pinned", is_starred=True, pinned_time=1700000050, is_archived=False, is_temporary_chat=False),
        "conv-not-pinned": _conv("conv-not-pinned", is_starred=False),
        "conv-archived": _conv("conv-archived", is_archived=True),
    }}
    out = tmp_path / "chatgpt_merged.json"
    out.write_text(json.dumps(merged), encoding="utf-8")
    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(out)
    by_id = {c.conversation_id: c for c in parser.conversations}
    assert by_id["conv-pinned"].is_pinned is True
    assert by_id["conv-not-pinned"].is_pinned is False
    assert by_id["conv-archived"].is_archived is True
    assert by_id["conv-archived"].is_pinned is None  # is_starred ausente


def test_save_writes_parquets_with_source_prefix(tmp_path):
    """Paths source-prefixed: data/processed/ChatGPT/chatgpt_<table>.parquet
    (alinha com claude_ai/qwen/deepseek/gemini/perplexity)."""
    merged = _make_merged("raw_with_voice.json", tmp_path)
    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(merged)
    out = tmp_path / "out"
    parser.save(out)
    assert (out / "chatgpt_conversations.parquet").is_file()
    assert (out / "chatgpt_messages.parquet").is_file()
    # tool_events pode ou nao existir dependendo da fixture; voice nao tem


# ============================================================
# Branches (Fase 2b)
# ============================================================

def test_parse_branches_extracts_branch_table(tmp_path):
    parser = _parse("raw_with_branches.json", tmp_path)
    assert parser.branches, "fixture branches deve gerar entries em parser.branches"
    # Pelo menos 2 branches (main + 1 fork minimo)
    assert len(parser.branches) >= 2


def test_parse_branches_active_marks_current_node(tmp_path):
    parser = _parse("raw_with_branches.json", tmp_path)
    actives = [b for b in parser.branches if b.is_active]
    assert len(actives) == 1, f"deve existir exatamente 1 branch ativa, achei {len(actives)}"


def test_parse_branches_main_has_no_parent(tmp_path):
    parser = _parse("raw_with_branches.json", tmp_path)
    main_branches = [b for b in parser.branches if b.parent_branch_id is None]
    assert main_branches, "deve existir pelo menos 1 branch sem parent (main)"
    # Convencao: branch_id = '<conv>_main' pra principal
    assert any(b.branch_id.endswith("_main") for b in main_branches)


def test_parse_branches_forks_have_parent(tmp_path):
    parser = _parse("raw_with_branches.json", tmp_path)
    forks = [b for b in parser.branches if b.parent_branch_id is not None]
    assert forks, "fixture branches tem fork — deve gerar pelo menos 1 sub-branch"


def test_parse_messages_get_correct_branch_id(tmp_path):
    parser = _parse("raw_with_branches.json", tmp_path)
    branch_ids = {b.branch_id for b in parser.branches}
    msg_branch_ids = {m.branch_id for m in parser.messages}
    # Toda branch_id em msgs deve existir na tabela branches
    assert msg_branch_ids.issubset(branch_ids), (
        f"branch_ids em messages nao previstas: {msg_branch_ids - branch_ids}"
    )


def test_parse_no_fork_yields_single_main_branch(tmp_path):
    """Conv sem fork (todos os nodes 0 ou 1 child) tem 1 branch só."""
    fake_conv = {
        "id": "linear-1", "title": "test",
        "create_time": 1700000000, "update_time": 1700000100,
        "current_node": "n3",
        "mapping": {
            "n0": {"id": "n0", "parent": None, "children": ["n1"], "message": None},
            "n1": {"id": "n1", "parent": "n0", "children": ["n2"],
                   "message": {"id": "n1", "create_time": 1700000010,
                               "author": {"role": "user"},
                               "content": {"content_type": "text", "parts": ["a"]},
                               "metadata": {}}},
            "n2": {"id": "n2", "parent": "n1", "children": ["n3"],
                   "message": {"id": "n2", "create_time": 1700000020,
                               "author": {"role": "assistant"},
                               "content": {"content_type": "text", "parts": ["b"]},
                               "metadata": {}}},
            "n3": {"id": "n3", "parent": "n2", "children": [],
                   "message": {"id": "n3", "create_time": 1700000030,
                               "author": {"role": "user"},
                               "content": {"content_type": "text", "parts": ["c"]},
                               "metadata": {}}},
        },
    }
    merged = tmp_path / "chatgpt_merged.json"
    merged.write_text(json.dumps({"conversations": {"linear-1": fake_conv}}))
    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(merged)
    assert len(parser.branches) == 1
    assert parser.branches[0].branch_id == "linear-1_main"
    assert parser.branches[0].is_active is True
    assert all(m.branch_id == "linear-1_main" for m in parser.messages)


def test_parse_fork_yields_three_branches(tmp_path):
    """Conv com 1 fork (2 children) gera 3 branches: main + 2 sub."""
    fake_conv = {
        "id": "fork-1", "title": "test",
        "create_time": 1700000000, "update_time": 1700000100,
        "current_node": "alt",
        "mapping": {
            "n0": {"id": "n0", "parent": None, "children": ["n1"], "message": None},
            "n1": {"id": "n1", "parent": "n0", "children": ["main-c", "alt"],
                   "message": {"id": "n1", "create_time": 1700000010,
                               "author": {"role": "user"},
                               "content": {"content_type": "text", "parts": ["q"]},
                               "metadata": {}}},
            "main-c": {"id": "main-c", "parent": "n1", "children": [],
                       "message": {"id": "main-c", "create_time": 1700000020,
                                   "author": {"role": "assistant"},
                                   "content": {"content_type": "text", "parts": ["resposta1"]},
                                   "metadata": {}}},
            "alt": {"id": "alt", "parent": "n1", "children": [],
                    "message": {"id": "alt", "create_time": 1700000025,
                                "author": {"role": "assistant"},
                                "content": {"content_type": "text", "parts": ["resposta2"]},
                                "metadata": {}}},
        },
    }
    merged = tmp_path / "chatgpt_merged.json"
    merged.write_text(json.dumps({"conversations": {"fork-1": fake_conv}}))
    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(merged)

    branch_ids = {b.branch_id for b in parser.branches}
    assert branch_ids == {"fork-1_main", "fork-1_main-c", "fork-1_alt"}, branch_ids

    # is_active aponta pro alt (current_node)
    actives = [b for b in parser.branches if b.is_active]
    assert len(actives) == 1
    assert actives[0].branch_id == "fork-1_alt"

    # parent_branch_id de main-c e alt aponta pra main
    by_id = {b.branch_id: b for b in parser.branches}
    assert by_id["fork-1_main"].parent_branch_id is None
    assert by_id["fork-1_main-c"].parent_branch_id == "fork-1_main"
    assert by_id["fork-1_alt"].parent_branch_id == "fork-1_main"

    # Msgs em main-c e alt em suas respectivas branches
    msg_branches = {m.message_id: m.branch_id for m in parser.messages}
    assert msg_branches.get("main-c") == "fork-1_main-c"
    assert msg_branches.get("alt") == "fork-1_alt"
    assert msg_branches.get("n1") == "fork-1_main"


def test_parse_branches_saved_in_parquet(tmp_path):
    merged = _make_merged("raw_with_branches.json", tmp_path)
    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(merged)
    out = tmp_path / "out"
    parser.save(out)
    assert (out / "chatgpt_branches.parquet").is_file()


def test_parse_preservation_fields_present(tmp_path):
    """is_preserved_missing e last_seen_in_server devem ser preenchidos quando
    _last_seen_in_server existe no merged."""
    fake_conv = {
        "id": "preserved-1", "title": "old",
        "create_time": 1700000000, "update_time": 1700000100,
        "_last_seen_in_server": "2026-04-20",  # antes do max
        "current_node": "root",
        "mapping": {
            "root": {"id": "root", "parent": None, "children": [],
                     "message": {"id": "root", "create_time": 1700000000,
                                 "author": {"role": "user"},
                                 "content": {"content_type": "text", "parts": ["oi"]},
                                 "metadata": {}}},
        },
    }
    fresh_conv = dict(fake_conv)
    fresh_conv["id"] = "fresh-1"
    fresh_conv["_last_seen_in_server"] = "2026-04-28"
    merged = tmp_path / "chatgpt_merged.json"
    merged.write_text(json.dumps({"conversations": {
        "preserved-1": fake_conv,
        "fresh-1": fresh_conv,
    }}))
    parser = ChatGPTParser(raw_root=tmp_path)
    parser.parse(merged)
    by_id = {c.conversation_id: c for c in parser.conversations}
    assert by_id["preserved-1"].is_preserved_missing is True
    assert by_id["fresh-1"].is_preserved_missing is False
    assert by_id["preserved-1"].last_seen_in_server is not None
