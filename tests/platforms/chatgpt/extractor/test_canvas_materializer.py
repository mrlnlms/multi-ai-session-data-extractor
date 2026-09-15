import json

from src.platforms.chatgpt.extractor.canvas_materializer import replay_canvas_snapshots
from src.platforms.chatgpt.extractor.asset_downloader import extract_canvases


def _message(message_id, role, *, recipient=None, name=None, payload="", create_time=0):
    author = {"role": role}
    if name:
        author["name"] = name
    message = {
        "id": message_id,
        "author": author,
        "content": {"content_type": "text", "parts": [payload]},
        "create_time": create_time,
    }
    if recipient:
        message["recipient"] = recipient
    return message


def _linear_conversation(*messages):
    mapping = {}
    previous = None
    for message in messages:
        node_id = message["id"]
        mapping[node_id] = {
            "id": node_id,
            "parent": previous,
            "children": [],
            "message": message,
        }
        if previous:
            mapping[previous]["children"].append(node_id)
        previous = node_id
    return {"id": "conversation-1", "mapping": mapping}


def test_replay_recovers_native_id_and_applies_successful_update():
    create = _message(
        "create-1", "assistant", recipient="canmore.create_textdoc", create_time=1,
        payload=json.dumps({"name": "report", "type": "document", "content": "Hello world"}),
    )
    created = _message(
        "create-result", "tool", name="canmore.create_textdoc", create_time=2,
        payload=("Successfully created text document 'Report' which will be referenced in all "
                 "future messages with the unique identifier textdoc_id: 'native-doc-1'"),
    )
    update = _message(
        "update-1", "assistant", recipient="canmore.update_textdoc", create_time=3,
        payload=json.dumps({"updates": [{"pattern": "world", "replacement": "Canvas"}]}),
    )
    updated = _message(
        "update-result", "tool", name="canmore.update_textdoc", create_time=4,
        payload="Successfully updated text document with textdoc_id 'native-doc-1'",
    )

    snapshots, report = replay_canvas_snapshots(_linear_conversation(create, created, update, updated))

    assert [item.content for item in snapshots] == ["Hello world", "Hello Canvas"]
    assert {item.document_id for item in snapshots} == {"native-doc-1"}
    assert snapshots[1].request_message_id == "update-1"
    assert snapshots[1].response_message_id == "update-result"
    assert report == {
        "creates": 1, "updates": 1, "snapshots": 2, "failed_upstream": 0,
        "unreconstructable": 0, "ambiguous": 0,
    }


def test_replay_skips_failed_update_and_preserves_create_state():
    create = _message(
        "create-1", "assistant", recipient="canmore.create_textdoc", create_time=1,
        payload=json.dumps({"name": "code.py", "type": "code", "content": "x = 1"}),
    )
    created = _message(
        "create-result", "tool", name="canmore.create_textdoc", create_time=2,
        payload=json.dumps({"result": "Successfully created text document", "textdoc_id": "doc-1"}),
    )
    update = _message(
        "update-1", "assistant", recipient="canmore.update_textdoc", create_time=3,
        payload=json.dumps({"updates": [{"pattern": "1", "replacement": "2"}]}),
    )
    failed = _message(
        "update-result", "tool", name="canmore.update_textdoc", create_time=4,
        payload="Failed with error. Fix the error and try again before replying to the user.",
    )

    snapshots, report = replay_canvas_snapshots(_linear_conversation(create, created, update, failed))

    assert [item.content for item in snapshots] == ["x = 1"]
    assert report["failed_upstream"] == 1


def test_replay_marks_successful_no_match_as_unreconstructable():
    create = _message(
        "create-1", "assistant", recipient="canmore.create_textdoc", create_time=1,
        payload=json.dumps({"name": "report", "type": "document", "content": "alpha"}),
    )
    created = _message(
        "create-result", "tool", name="canmore.create_textdoc", create_time=2,
        payload=json.dumps({"result": "Successfully created", "textdoc_id": "doc-1"}),
    )
    update = _message(
        "update-1", "assistant", recipient="canmore.update_textdoc", create_time=3,
        payload=json.dumps({"updates": [{"pattern": "missing", "replacement": "beta"}]}),
    )
    updated = _message(
        "update-result", "tool", name="canmore.update_textdoc", create_time=4,
        payload=json.dumps({"result": "Successfully updated", "textdoc_id": "doc-1"}),
    )

    snapshots, report = replay_canvas_snapshots(_linear_conversation(create, created, update, updated))

    assert [item.content for item in snapshots] == ["alpha"]
    assert report["unreconstructable"] == 1


def test_replay_uses_exact_legacy_payload_fallback_for_empty_request():
    create = _message(
        "create-1", "assistant", recipient="canmore.create_textdoc", create_time=1,
        payload="",
    )
    created = _message(
        "create-result", "tool", name="canmore.create_textdoc", create_time=2,
        payload=("Successfully created text document with the unique identifier "
                 "textdoc_id: 'doc-legacy'"),
    )

    snapshots, report = replay_canvas_snapshots(
        _linear_conversation(create, created),
        {"create-1": {"name": "legacy", "type": "document", "content": "recovered"}},
    )

    assert [(item.document_id, item.content) for item in snapshots] == [("doc-legacy", "recovered")]
    assert report["unreconstructable"] == 0


def test_replay_recovers_after_unknown_state_with_full_replacement():
    create = _message(
        "create-1", "assistant", recipient="canmore.create_textdoc", create_time=1,
        payload="",
    )
    created = _message(
        "create-result", "tool", name="canmore.create_textdoc", create_time=2,
        payload="Successfully created text document with textdoc_id 'doc-1'",
    )
    update = _message(
        "update-1", "assistant", recipient="canmore.update_textdoc", create_time=3,
        payload=json.dumps({"updates": [{"pattern": ".*", "replacement": "complete replacement"}]}),
    )
    updated = _message(
        "update-result", "tool", name="canmore.update_textdoc", create_time=4,
        payload="Successfully updated text document with textdoc_id 'doc-1'",
    )

    snapshots, report = replay_canvas_snapshots(_linear_conversation(create, created, update, updated))

    assert [(item.version, item.content) for item in snapshots] == [(1, "complete replacement")]
    assert report["unreconstructable"] == 1


def test_replay_uses_multiple_flag_and_is_branch_aware():
    create = _message(
        "create-1", "assistant", recipient="canmore.create_textdoc", create_time=1,
        payload=json.dumps({"name": "report", "type": "document", "content": "a a"}),
    )
    created = _message(
        "create-result", "tool", name="canmore.create_textdoc", create_time=2,
        payload=json.dumps({"result": "Successfully created", "textdoc_id": "doc-1"}),
    )
    conv = _linear_conversation(create, created)
    mapping = conv["mapping"]
    for suffix, replacement in (("left", "L"), ("right", "R")):
        request = _message(
            f"update-{suffix}", "assistant", recipient="canmore.update_textdoc", create_time=3,
            payload=json.dumps({"updates": [{"pattern": "a", "replacement": replacement, "multiple": True}]}),
        )
        response = _message(
            f"result-{suffix}", "tool", name="canmore.update_textdoc", create_time=4,
            payload=json.dumps({"result": "Successfully updated", "textdoc_id": "doc-1"}),
        )
        mapping[request["id"]] = {"id": request["id"], "parent": "create-result", "children": [response["id"]], "message": request}
        mapping[response["id"]] = {"id": response["id"], "parent": request["id"], "children": [], "message": response}
        mapping["create-result"]["children"].append(request["id"])

    snapshots, report = replay_canvas_snapshots(conv)

    assert {item.content for item in snapshots[1:]} == {"L L", "R R"}
    assert report["ambiguous"] == 0


def test_extract_materializes_replay_snapshots_idempotently(tmp_path):
    create = _message(
        "create-1", "assistant", recipient="canmore.create_textdoc", create_time=1,
        payload=json.dumps({"name": "page.html", "type": "html", "content": "<p>one</p>"}),
    )
    created = _message(
        "create-result", "tool", name="canmore.create_textdoc", create_time=2,
        payload=json.dumps({"result": "Successfully created", "textdoc_id": "doc-1"}),
    )
    raw = {"conversations": {"conversation-1": _linear_conversation(create, created)}}
    (tmp_path / "chatgpt_raw.json").write_text(json.dumps(raw), encoding="utf-8")

    first = extract_canvases(tmp_path)
    second = extract_canvases(tmp_path)

    [snapshot] = list((tmp_path / "assets" / "canvases").glob("*/*.html"))
    metadata = json.loads(snapshot.with_suffix(".html.meta.json").read_text(encoding="utf-8"))
    assert snapshot.read_text(encoding="utf-8") == "<p>one</p>"
    assert metadata["asset_id"] == "canvas:doc-1:create-1"
    assert metadata["message_id"] == "create-1"
    assert first["extracted"] == 1
    assert second["skipped_existing"] == 1


def test_extract_never_overwrites_distinct_existing_snapshot(tmp_path):
    create = _message(
        "create-1", "assistant", recipient="canmore.create_textdoc", create_time=1,
        payload=json.dumps({"name": "report", "type": "document", "content": "canonical"}),
    )
    created = _message(
        "create-result", "tool", name="canmore.create_textdoc", create_time=2,
        payload=json.dumps({"result": "Successfully created", "textdoc_id": "doc-1"}),
    )
    raw = {"conversations": {"conversation-1": _linear_conversation(create, created)}}
    (tmp_path / "chatgpt_raw.json").write_text(json.dumps(raw), encoding="utf-8")
    first = extract_canvases(tmp_path)
    [snapshot] = list((tmp_path / "assets" / "canvases").glob("*/*.md"))
    snapshot.write_text("different preserved bytes", encoding="utf-8")

    second = extract_canvases(tmp_path, skip_existing=False)

    assert first["extracted"] == 1
    assert second["extracted"] == 0
    assert second["errors"]
    assert snapshot.read_text(encoding="utf-8") == "different preserved bytes"
