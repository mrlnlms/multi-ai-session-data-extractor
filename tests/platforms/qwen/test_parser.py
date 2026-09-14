"""Testes do parser Qwen v3 (schema canonico).

Cobertura:
- Layout merged (data/merged/Qwen/conversations/<uuid>.json envelopes)
- 8 chat_types mapeando pra modes validos
- pinned/archived/temporary flags
- reasoning_content → Message.thinking
- Branches via parentId/childrenIds + currentId
- Search results → ToolEvent
- t2i/t2v/artifacts → image/video_generation_call
- Files → attachment_names
- Project com custom_instruction + _files → metadata + docs
- Preservation
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.platforms.qwen.parser import QwenParser


ACCOUNT_ID = "810f3e91-ae10-5cb1-931a-53b80630af16"


def _write_merged(tmp_path: Path, convs_envelopes: list[dict], projects: list[dict] | None = None) -> Path:
    merged = tmp_path / "data/merged/Qwen"
    (merged / "conversations").mkdir(parents=True, exist_ok=True)
    for env in convs_envelopes:
        cid = env["data"]["id"]
        (merged / "conversations" / f"{cid}.json").write_text(
            json.dumps(env, ensure_ascii=False), encoding="utf-8"
        )
    if projects:
        (merged / "projects.json").write_text(
            json.dumps(projects, ensure_ascii=False), encoding="utf-8"
        )
    return merged


def _basic_conv(cid="conv-1", chat_type="t2t", **data_overrides) -> dict:
    """Envelope Qwen completo: {success, request_id, data: {...}}"""
    msg_user_id = "msg-1"
    msg_asst_id = "msg-2"
    data = {
        "id": cid,
        "title": "Test Chat",
        "chat_type": chat_type,
        "pinned": False,
        "archived": False,
        "project_id": None,
        "currentId": msg_asst_id,
        "currentResponseIds": [msg_asst_id],
        "user_id": "u-1",
        "created_at": "1777088048",
        "updated_at": "1777088096",
        "share_id": None,
        "folder_id": None,
        "models": None,
        "meta": {"timestamp": 1777088048, "tags": ["work"]},
        "chat": {
            "history": {
                "messages": {
                    msg_user_id: {
                        "id": msg_user_id,
                        "parentId": None,
                        "childrenIds": [msg_asst_id],
                        "role": "user",
                        "content": "hello",
                        "content_list": [{"content": "hello", "timestamp": 1777088050}],
                        "timestamp": 1777088050,
                        "model": "",
                        "feature_config": {"web_search": False},
                    },
                    msg_asst_id: {
                        "id": msg_asst_id,
                        "parentId": msg_user_id,
                        "childrenIds": [],
                        "role": "assistant",
                        "content": "hi there",
                        "content_list": [{"content": "hi there", "timestamp": 1777088060}],
                        "timestamp": 1777088060,
                        "model": "qwen3-max-preview",
                        "modelName": "Qwen3-Max",
                    },
                },
            },
        },
    }
    data.update(data_overrides)
    return {"success": True, "request_id": "r-1", "data": data}


def test_basic_parse(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv()])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    assert len(p.conversations) == 1
    assert len(p.messages) == 2
    c = p.conversations[0]
    assert c.conversation_id == "conv-1"
    assert c.source == "qwen"
    assert c.title == "Test Chat"
    assert c.mode == "chat"
    assert c.url == "https://chat.qwen.ai/c/conv-1"


def test_chat_type_to_mode_mapping(tmp_path):
    cases = [
        ("t2t", "chat"),
        ("search", "search"),
        ("deep_research", "research"),
        ("t2i", "dalle"),
        ("t2v", "dalle"),
        ("artifacts", "chat"),
        ("learn", "chat"),
    ]
    convs = [_basic_conv(cid=f"conv-{i}", chat_type=ct) for i, (ct, _) in enumerate(cases)]
    merged = _write_merged(tmp_path, convs)
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    by_id = {c.conversation_id: c for c in p.conversations}
    for i, (ct, expected) in enumerate(cases):
        assert by_id[f"conv-{i}"].mode == expected, f"chat_type={ct}"


def test_pinned_archived_flags(tmp_path):
    convs = [
        _basic_conv(cid="conv-pinned", pinned=True),
        _basic_conv(cid="conv-archived", archived=True),
    ]
    merged = _write_merged(tmp_path, convs)
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    by_id = {c.conversation_id: c for c in p.conversations}
    assert by_id["conv-pinned"].is_pinned is True
    assert by_id["conv-archived"].is_archived is True


def test_empty_project_id_becomes_none(tmp_path):
    """project_id='' (string vazia, frequente no Qwen) → None."""
    merged = _write_merged(tmp_path, [_basic_conv(project_id="")])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    assert p.conversations[0].project_id is None


def test_settings_json_meta_and_feature_config(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv()])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    settings = json.loads(p.conversations[0].settings_json)
    assert settings["meta"]["tags"] == ["work"]
    assert settings["feature_config"]["web_search"] is False


def test_reasoning_content_to_thinking(tmp_path):
    conv = _basic_conv()
    asst = conv["data"]["chat"]["history"]["messages"]["msg-2"]
    asst["reasoning_content"] = "Let me think... step 1, step 2."
    merged = _write_merged(tmp_path, [conv])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    msg_asst = next(m for m in p.messages if m.role == "assistant")
    assert msg_asst.thinking == "Let me think... step 1, step 2."


def test_branches_via_parentId_currentId(tmp_path):
    conv = _basic_conv(cid="conv-fork")
    msgs = conv["data"]["chat"]["history"]["messages"]
    msgs["msg-3"] = {
        "id": "msg-3",
        "parentId": "msg-1",
        "childrenIds": [],
        "role": "assistant",
        "content": "alternative",
        "content_list": [],
        "timestamp": 1777088070,
        "model": "qwen-alt",
    }
    msgs["msg-1"]["childrenIds"] = ["msg-2", "msg-3"]
    merged = _write_merged(tmp_path, [conv])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    branches = {b.branch_id: b for b in p.branches}
    assert "conv-fork_main" in branches
    assert any(bid.startswith("conv-fork_branch_") for bid in branches)
    msg3 = next(m for m in p.messages if m.message_id == "msg-3")
    assert msg3.branch_id != "conv-fork_main"


def test_search_results_to_tool_event(tmp_path):
    conv = _basic_conv(chat_type="search")
    asst = conv["data"]["chat"]["history"]["messages"]["msg-2"]
    asst["info"] = {
        "search_results": [
            {"title": "Result 1", "url": "https://example.com"},
            {"title": "Result 2", "url": "https://example.org"},
        ],
    }
    merged = _write_merged(tmp_path, [conv])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    assert len(p.events) == 2
    call = next(e for e in p.events if e.event_type == "search_call")
    result = next(e for e in p.events if e.event_type == "search_result")
    assert call.tool_name == "search"
    results_data = json.loads(result.result)
    assert len(results_data) == 2


def test_t2i_emits_image_generation_event(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv(chat_type="t2i")])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    img = [e for e in p.events if e.event_type == "image_generation_call"]
    assert len(img) == 1


def test_files_to_attachment_names(tmp_path):
    conv = _basic_conv()
    user_msg = conv["data"]["chat"]["history"]["messages"]["msg-1"]
    user_msg["files"] = [{"name": "file1.pdf"}, {"name": "image.png"}]
    merged = _write_merged(tmp_path, [conv])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    msg_user = next(m for m in p.messages if m.role == "user")
    names = json.loads(msg_user.attachment_names)
    assert "file1.pdf" in names
    assert "image.png" in names


def test_block_timestamps(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv()])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    msg_asst = next(m for m in p.messages if m.role == "assistant")
    assert msg_asst.start_timestamp is not None
    assert msg_asst.stop_timestamp is not None


def test_project_metadata_and_docs(tmp_path):
    conv = _basic_conv(project_id="proj-1")
    project = {
        "id": "proj-1",
        "name": "Test Project",
        "icon": "icon=📚",
        "memory_span": "default",
        "custom_instruction": "Be helpful.",
        "created_at": 1777088000,
        "updated_at": 1777088100,
        "_files": [
            {
                "file_id": "f-1",
                "file_name": "doc.pdf",
                "size": 12345,
                "file_type": "application/pdf",
                "created_at": 1777088000,
            },
        ],
    }
    merged = _write_merged(tmp_path, [conv], projects=[project])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    pmeta = p.project_metadata_df()
    assert len(pmeta) == 1
    assert pmeta.iloc[0]["custom_instruction"] == "Be helpful."
    pdocs = p.project_docs_df()
    assert len(pdocs) == 1
    assert pdocs.iloc[0]["file_name"] == "doc.pdf"
    assert pdocs.iloc[0]["content_size"] == 12345


def test_assets_deduplicate_rotated_urls_and_emit_evidenced_links(tmp_path):
    upload_url = "https://cdn.qwenlm.ai/user/upload?token=secret"
    generated_url = "https://cdn.qwenlm.ai/output/generated.png?signature=secret"
    project_url_1 = "https://oss.aliyuncs.com/project?signature=old"
    project_url_2 = "https://oss.aliyuncs.com/project?signature=new"
    conv = _basic_conv()
    user = conv["data"]["chat"]["history"]["messages"]["msg-1"]
    assistant = conv["data"]["chat"]["history"]["messages"]["msg-2"]
    user["files"] = [{"id": "upload-1", "name": "input.pdf", "url": upload_url}]
    assistant["content_list"] = [{"content": generated_url, "timestamp": 1777088060}]
    project = {
        "id": "project-1", "name": "Project", "_files": [{
            "file_id": "project-file-1", "file_name": "source.md",
            "path": project_url_2, "size": 7,
        }],
    }
    merged = _write_merged(tmp_path, [conv], projects=[project])
    assets_dir = merged / "assets"
    files = {
        "conv-1/input.pdf": b"upload",
        "conv-1/generated.png": b"generated",
        "_project_project-1/source-old.md": b"project",
        "_project_project-1/source-new.md": b"project",
    }
    for relpath, content in files.items():
        path = assets_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {
        "upload-key": {"url": upload_url, "conv_id": "conv-1", "source_type": "user_upload", "file_class": "document", "file_name": "input.pdf", "file_id": "upload-1", "content_type": "application/pdf", "size": 6, "relpath": "conv-1/input.pdf"},
        "generated-key": {"url": generated_url, "conv_id": "conv-1", "source_type": "generated", "file_class": "t2i", "file_name": None, "file_id": None, "content_type": "image/png", "size": 9, "relpath": "conv-1/generated.png"},
        "project-old": {"url": project_url_1, "conv_id": "_project_project-1", "source_type": "project_file", "file_class": None, "file_name": "source.md", "file_id": "project-file-1", "content_type": "text/markdown", "size": 7, "relpath": "_project_project-1/source-old.md"},
        "project-new": {"url": project_url_2, "conv_id": "_project_project-1", "source_type": "project_file", "file_class": None, "file_name": "source.md", "file_id": "project-file-1", "content_type": "text/markdown", "size": 7, "relpath": "_project_project-1/source-new.md"},
    }
    (merged / "assets_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    p = QwenParser(account_id=ACCOUNT_ID, merged_root=merged)
    p.parse(merged)
    assets = p.assets_df()
    links = p.asset_links_df()

    assert len(assets) == 3
    assert set(assets["asset_kind"]) == {"attachment", "generated", "project_file"}
    assert set(assets["asset_origin"]) == {"user", "assistant"}
    assert assets["asset_id"].str.startswith("sha256:").sum() == 1
    assert set(links["object_type"]) == {"message", "source"}
    assert set(links["role"]) == {"input", "output", "context"}
    assert links["asset_link_id"].is_unique
    generated_link = links.loc[links["role"] == "output"].iloc[0]
    assert generated_link["message_id"] == "msg-2"
    assert generated_link["content_block_index"] == 0
    project_link = links.loc[links["object_type"] == "source"].iloc[0]
    assert project_link["object_id"] == "project-file-1"
    assert project_link["project_id"] == "project-1"
    serialized = assets.to_json() + links.to_json()
    assert "token=secret" not in serialized
    assert "signature=" not in serialized


def test_save_writes_parquets(tmp_path):
    merged = _write_merged(tmp_path, [_basic_conv()])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    out = tmp_path / "processed"
    p.save(out)
    assert (out / "qwen_conversations.parquet").exists()
    assert (out / "qwen_messages.parquet").exists()
    assert (out / "qwen_branches.parquet").exists()
    assert (out / "qwen_assets.parquet").exists()
    assert (out / "qwen_asset_links.parquet").exists()


def test_preservation_via_explicit_flag(tmp_path):
    env = _basic_conv()
    env["_preserved_missing"] = True
    env["_last_seen_in_server"] = "2026-04-01"
    merged = _write_merged(tmp_path, [env])
    p = QwenParser(merged_root=merged)
    p.parse(merged)
    assert p.conversations[0].is_preserved_missing is True
