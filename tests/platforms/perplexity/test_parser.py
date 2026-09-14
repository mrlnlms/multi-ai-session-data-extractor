"""Testes do PerplexityParser v3 (consume merged_dir cumulativo)."""

import json
import hashlib
import pandas as pd
from pathlib import Path

from src.platforms.perplexity.parser import PerplexityParser


def _make_thread(uid: str, mode: str, title: str, entries: list[dict]) -> dict:
    return {
        "status": "success",
        "entries": entries,
        "background_entries": [],
        "_last_seen_in_server": "2026-05-01",
    }


def _write_merged(tmp_path: Path, threads: dict[str, dict], discovery: list[dict] | None = None,
                  spaces: list[dict] | None = None, assets: list[dict] | None = None):
    """Cria estrutura merged em tmp_path."""
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True)
    for uid, data in threads.items():
        (threads_dir / f"{uid}.json").write_text(json.dumps(data, ensure_ascii=False))
    if discovery is not None:
        (tmp_path / "threads_discovery.json").write_text(json.dumps(discovery, ensure_ascii=False))
    if spaces:
        spaces_dir = tmp_path / "spaces"
        spaces_dir.mkdir(parents=True)
        for s in spaces:
            sd = spaces_dir / s["uuid"]
            sd.mkdir()
            (sd / "metadata.json").write_text(json.dumps(s, ensure_ascii=False))
            (sd / "threads_index.json").write_text(json.dumps(s.get("_threads_in", []), ensure_ascii=False))
    if assets is not None:
        ad = tmp_path / "assets"
        ad.mkdir(parents=True)
        (ad / "_index.json").write_text(json.dumps(assets, ensure_ascii=False))


def _entry(uuid: str, query: str, mode: str = "COPILOT", title: str | None = None,
           sources: list[dict] | None = None, attachments: list[str] | None = None) -> dict:
    return {
        "uuid": uuid,
        "thread_title": title or query,
        "mode": mode,
        "query_str": query,
        "display_model": "turbo",
        "entry_created_datetime": "2025-09-05T10:12:00.000000+00:00",
        "entry_updated_datetime": "2025-09-05T10:12:00.000000+00:00",
        "blocks": [
            {"answer": "Response to: " + query},
            {"web_result_block": {"web_results": sources or [], "progress": "DONE"}},
        ] if sources else [{"answer": "Response to: " + query}],
        "attachments": attachments or [],
        "media_items": [],
        "featured_images": [],
    }


def test_parser_basic_thread(tmp_path):
    threads = {
        "t1": _make_thread("t1", "COPILOT", "HAI research", [
            _entry("e1", "What is HAI?", title="HAI research"),
        ]),
    }
    _write_merged(tmp_path, threads)

    p = PerplexityParser(merged_root=tmp_path)
    p.parse()

    assert len(p.conversations) == 1
    assert len(p.messages) == 2  # 1 entry = user + assistant
    assert len(p.branches) == 1

    conv = p.conversations[0]
    assert conv.conversation_id == "t1"
    assert conv.source == "perplexity"
    assert conv.title == "HAI research"
    assert conv.mode == "copilot"
    assert conv.message_count == 2


def test_parser_mode_mapping(tmp_path):
    threads = {
        "t1": _make_thread("t1", "CONCISE", "Quick", [_entry("e1", "Q1", mode="CONCISE")]),
        "t2": _make_thread("t2", "COPILOT", "Deep", [_entry("e2", "Q2", mode="COPILOT")]),
        "t3": _make_thread("t3", "ASI", "Comp", [_entry("e3", "Q3", mode="ASI")]),
    }
    _write_merged(tmp_path, threads)

    p = PerplexityParser(merged_root=tmp_path)
    p.parse()

    modes = {c.conversation_id: c.mode for c in p.conversations}
    assert modes["t1"] == "concise"
    assert modes["t2"] == "copilot"
    assert modes["t3"] == "research"


def test_parser_search_results_to_tool_events(tmp_path):
    threads = {
        "t1": _make_thread("t1", "COPILOT", "Search test", [
            _entry("e1", "Search Q", sources=[
                {"url": "https://a.com", "name": "A", "snippet": "Snip A"},
                {"url": "https://b.com", "name": "B", "snippet": "Snip B"},
            ]),
        ]),
    }
    _write_merged(tmp_path, threads)

    p = PerplexityParser(merged_root=tmp_path)
    p.parse()

    sr = [te for te in p.tool_events if te.event_type == "search_result"]
    assert len(sr) == 2
    md = [te.metadata_json for te in sr]
    assert all("a.com" in m or "b.com" in m for m in md)


def test_parser_thread_in_space_links_project(tmp_path):
    threads = {
        "t1": _make_thread("t1", "COPILOT", "In space", [_entry("e1", "Q")]),
    }
    spaces = [{
        "uuid": "space-uuid",
        "title": "MySpace",
        "slug": "my-space",
        "_threads_in": [{"uuid": "t1", "mode": "copilot", "title": "In space"}],
    }]
    _write_merged(tmp_path, threads, spaces=spaces)

    p = PerplexityParser(merged_root=tmp_path)
    p.parse()

    conv = next(c for c in p.conversations if c.conversation_id == "t1")
    assert conv.project == "space-uuid"
    assert conv.project_id == "space-uuid"


def test_parser_assets_to_tool_events(tmp_path):
    threads = {"t1": _make_thread("t1", "COPILOT", "T", [_entry("e1", "Q")])}
    assets = [
        {"asset_slug": "doc-md-abc123", "asset_type": "CODE_FILE",
         "entry_uuid": "e1", "caption": "doc.md"},
        {"asset_slug": "img-png-xyz789", "asset_type": "GENERATED_IMAGE",
         "entry_uuid": "e1", "caption": "image"},
    ]
    _write_merged(tmp_path, threads, assets=assets)

    p = PerplexityParser(merged_root=tmp_path)
    p.parse()

    asset_events = [te for te in p.tool_events if te.event_type == "asset_generation"]
    assert len(asset_events) == 2
    types = sorted(te.tool_name for te in asset_events)
    assert types == ["CODE_FILE", "GENERATED_IMAGE"]


def test_artifact_emits_available_asset_and_exact_output_link(tmp_path):
    threads = {"t1": _make_thread("t1", "COPILOT", "T", [_entry("e1", "Q")])}
    assets = [{
        "asset_id": "native-1", "asset_slug": "report-abc", "asset_type": "CODE_FILE",
        "entry_uuid": "e1", "caption": "report.md", "preview_image_url": "https://secret.invalid/?token=x",
    }]
    _write_merged(tmp_path, threads, assets=assets)
    files = tmp_path / "assets" / "files"
    files.mkdir()
    (files / "report-abc.md").write_text("artifact")

    parser = PerplexityParser(merged_root=tmp_path)
    parser.parse()

    assert len(parser.assets) == 1
    asset = parser.assets[0]
    assert asset.asset_id == "native-1"
    assert asset.asset_kind == "artifact"
    assert asset.asset_origin == "assistant"
    assert asset.asset_path == "merged/Perplexity/assets/files/report-abc.md"
    assert asset.is_binary_available is True
    assert "token" not in (asset.metadata_json or "")
    link = parser.asset_links[0]
    assert link.object_id == "e1_asst"
    assert link.conversation_id == "t1"
    assert link.role == "output"


def test_failed_upload_is_retained_without_publishing_signed_url(tmp_path):
    signed = "https://ppl-ai-file-upload.s3.amazonaws.com/archive/source.pdf?X-Amz-Signature=secret"
    threads = {"t1": _make_thread("t1", "COPILOT", "T", [_entry("e1", "Q", attachments=[signed])])}
    _write_merged(tmp_path, threads)
    manifest = {
        hashlib.sha1(signed.encode()).hexdigest()[:16]: {
            "status": "failed_upstream_deleted", "source_type": "user_upload",
            "url_stale": signed, "error": "404 NoSuchKey",
        }
    }
    (tmp_path / "thread_attachments_manifest.json").write_text(json.dumps(manifest))

    parser = PerplexityParser(merged_root=tmp_path, raw_root=tmp_path)
    parser.parse()

    user = next(message for message in parser.messages if message.role == "user")
    assert user.asset_paths is None
    assert len(parser.assets) == 1
    asset = parser.assets[0]
    assert asset.asset_kind == "attachment"
    assert asset.asset_origin == "user"
    assert asset.is_preserved_missing is True
    assert asset.is_binary_available is False
    assert signed not in (asset.metadata_json or "")
    assert parser.asset_links[0].object_id == "e1_user"
    assert parser.asset_links[0].role == "input"


def test_external_featured_image_is_not_a_preserved_asset(tmp_path):
    entry = _entry("e1", "Q")
    entry["featured_images"] = ["https://external.example/image.jpg?token=secret"]
    threads = {"t1": _make_thread("t1", "COPILOT", "T", [entry])}
    _write_merged(tmp_path, threads)

    parser = PerplexityParser(merged_root=tmp_path)
    parser.parse()

    assistant = next(message for message in parser.messages if message.role == "assistant")
    assert assistant.asset_paths is None
    assert parser.assets == []
    assert parser.asset_links == []


def test_repeated_upload_reuses_asset_with_distinct_message_links(tmp_path):
    url = "https://ppl-ai-file-upload.s3.amazonaws.com/archive/shared.pdf?signature=one"
    threads = {"t1": _make_thread("t1", "COPILOT", "T", [
        _entry("e1", "Q1", attachments=[url]), _entry("e2", "Q2", attachments=[url]),
    ])}
    _write_merged(tmp_path, threads)

    parser = PerplexityParser(merged_root=tmp_path)
    parser.parse()

    assert len(parser.assets) == 1
    assert len(parser.asset_links) == 2
    assert {link.object_id for link in parser.asset_links} == {"e1_user", "e2_user"}
    assert len({link.asset_link_id for link in parser.asset_links}) == 2


def test_parser_preservation_flag(tmp_path):
    threads = {"t1": _make_thread("t1", "COPILOT", "Old", [_entry("e1", "Q")])}
    discovery = [
        {"uuid": "t1", "title": "Old", "last_query_datetime": "2025-09-05T10:12:00Z"},
        {"uuid": "deleted-uuid", "title": "Deleted thread", "last_query_datetime": "2025-01-01T00:00:00Z",
         "_preserved_missing": True},
    ]
    _write_merged(tmp_path, threads, discovery=discovery)

    p = PerplexityParser(merged_root=tmp_path)
    p.parse()

    # Deleted thread nao tem JSON file, mas se tivesse, is_preserved_missing seria True.
    # Aqui so validamos que threads existentes ficam com is_preserved_missing=False.
    assert all(not c.is_preserved_missing for c in p.conversations if c.conversation_id == "t1")


def test_save_writes_asset_graph_parquets(tmp_path):
    threads = {"t1": _make_thread("t1", "COPILOT", "T", [_entry("e1", "Q")])}
    _write_merged(tmp_path, threads, assets=[])
    parser = PerplexityParser(merged_root=tmp_path)
    parser.parse()
    output = tmp_path / "processed"
    parser.save(output)
    assert (output / "perplexity_assets.parquet").is_file()
    assert (output / "perplexity_asset_links.parquet").is_file()
