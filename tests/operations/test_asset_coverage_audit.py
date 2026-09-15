import json
from pathlib import Path

import pandas as pd
import pytest

from src.operations.asset_coverage_audit import (
    CoverageFinding,
    RepresentationEvidence,
    inventory_preserved_session_assets,
    iter_account_roots,
    load_policy,
    reconcile_asset_coverage,
    redacted_finding,
    summarize_findings,
)
from src.platforms.registry import KNOWN_PLATFORMS


def _fixture_archive(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    for source in KNOWN_PLATFORMS:
        root = data / "raw" / source
        (root / "assets").mkdir(parents=True)
        (root / "assets" / "private-name.bin").write_bytes(b"asset")
        (root / "capture_log.jsonl").write_text("{}\n")
        (root / "assets_manifest.json").write_text("{}")
        (root / "mystery.dat").write_bytes(b"?")
    claude = data / "raw" / "Claude Code" / "session.jsonl"
    claude.write_text(json.dumps({
        "type": "user", "uuid": "message-secret", "sessionId": "session-secret",
        "message": {"content": [{"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": "YWJj",
        }}]},
    }) + "\n")
    codex = data / "raw" / "Codex" / "rollout-test.jsonl"
    codex.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": "session"}}),
        json.dumps({"timestamp": "2026-01-01T00:00:00Z", "type": "response_item", "payload": {
            "type": "message", "role": "user",
            "content": [{"type": "input_image", "image_url": "data:image/png;base64,YWJj"}],
        }}),
    ]) + "\n")
    return data


def test_evidence_dataclass_has_exact_contract():
    assert list(RepresentationEvidence.__dataclass_fields__) == [
        "source", "account_scope", "representation_kind", "evidence_path",
        "native_id", "binary_path", "conversation_id", "message_id",
        "project_id", "observed_role",
    ]


def test_iter_account_roots_keeps_default_and_accounts_separate(tmp_path):
    root = tmp_path / "Source"
    (root / "account-2").mkdir(parents=True)
    (root / "ordinary").mkdir()
    assert [(scope, path.name) for scope, path in iter_account_roots(root)] == [
        ("default", "Source"), ("account-2", "account-2")
    ]


def test_inventory_accounts_for_all_13_sources_and_attachment_shapes(tmp_path):
    evidence = inventory_preserved_session_assets(_fixture_archive(tmp_path))
    assert {item.source for item in evidence} == set(KNOWN_PLATFORMS)
    assert any(item.source == "Claude Code" and item.representation_kind == "embedded_attachment" for item in evidence)
    assert any(item.source == "Codex" and item.representation_kind == "embedded_attachment" for item in evidence)


def test_project_sources_are_preserved_binary_candidates(tmp_path):
    data = tmp_path / "data"
    path = data / "raw" / "ChatGPT" / "project_sources" / "project" / "source.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"pdf")
    [item] = inventory_preserved_session_assets(data)
    assert item.representation_kind == "preserved_binary"


def test_cli_materialized_artifacts_are_preserved_binary_candidates(tmp_path):
    data = tmp_path / "data"
    path = data / "raw" / "Antigravity CLI" / "_artifacts" / "conv" / "report.md"
    path.parent.mkdir(parents=True)
    path.write_text("report")
    [item] = inventory_preserved_session_assets(data)
    assert item.representation_kind == "preserved_binary"


def test_malformed_session_evidence_is_never_silently_ignored(tmp_path):
    data = tmp_path / "data"
    path = data / "raw" / "Codex" / "broken.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not-json\n")
    evidence = inventory_preserved_session_assets(data)
    assert any(item.representation_kind == "malformed_evidence" for item in evidence)


def test_claude_code_jsonl_keeps_unicode_line_separator_inside_json_string(tmp_path):
    data = tmp_path / "data"
    path = data / "raw" / "Claude Code" / "project" / "session.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "type": "user", "uuid": "message", "sessionId": "session",
        "message": {"content": [{"type": "text", "text": "a\u2028b"}]},
    }, ensure_ascii=False) + "\n")
    evidence = inventory_preserved_session_assets(data)
    assert not any(item.representation_kind == "malformed_evidence" for item in evidence)


def test_every_fixture_lands_in_exactly_one_status(tmp_path):
    evidence = inventory_preserved_session_assets(_fixture_archive(tmp_path))
    covered = next(item.binary_path for item in evidence if item.source == "ChatGPT" and item.representation_kind == "preserved_binary")
    assets = pd.DataFrame({"asset_path": [covered]})
    findings = reconcile_asset_coverage(evidence, assets, pd.DataFrame())
    assert len(findings) == len(evidence)
    assert all(finding.status for finding in findings)
    assert sum(f.status == "covered" for f in findings) == 1


def test_tool_file_reference_never_becomes_eligible_without_copied_bytes():
    item = RepresentationEvidence("Codex", "default", "tool_file_reference", "raw/Codex/x.jsonl", None, None, None, None, None, None)
    [finding] = reconcile_asset_coverage([item], pd.DataFrame(), pd.DataFrame(), load_policy())
    assert finding.status == "excluded"
    assert finding.policy_disposition == "external_reference"


@pytest.mark.parametrize("kind", [
    "asset_manifest", "asset_metadata_sidecar", "domain_record",
    "cli_session_record", "agent_memory", "cli_operational_state",
    "storage_container",
])
def test_technical_evidence_is_accounted_for_but_not_an_asset(kind):
    item = RepresentationEvidence("ChatGPT", "default", kind, "raw/ChatGPT/record", None, None, None, None, None, None)
    rule = {"source": "ChatGPT", "representation_kind": kind, "disposition": "domain_only"}
    [finding] = reconcile_asset_coverage([item], pd.DataFrame(), pd.DataFrame(), [rule])
    assert finding.status == "excluded"


def test_json_output_is_asset_but_companion_metadata_is_not(tmp_path):
    data = tmp_path / "data"
    root = data / "raw" / "Claude.ai" / "assets" / "artifacts" / "conversation"
    root.mkdir(parents=True)
    (root / "output.json").write_text('{"result": true}')
    (root / "output.json.meta.json").write_text('{"artifact_id": "x"}')
    evidence = inventory_preserved_session_assets(data)
    assert {item.representation_kind for item in evidence} == {
        "preserved_binary", "asset_metadata_sidecar"
    }


def test_policy_is_exact_and_cannot_hide_eligible_binary():
    binary = RepresentationEvidence("ChatGPT", "default", "preserved_binary", "raw/ChatGPT/assets/x", None, "raw/ChatGPT/assets/x", None, None, None, None)
    rule = {"source": "ChatGPT", "representation_kind": "preserved_binary", "disposition": "cache"}
    [finding] = reconcile_asset_coverage([binary], pd.DataFrame(), pd.DataFrame(), [rule])
    assert finding.status == "eligible_uncovered"


def test_redacted_serialization_contains_no_paths_ids_filenames_or_content():
    item = RepresentationEvidence("ChatGPT", "account-private", "domain_record", "raw/ChatGPT/private-name.json", "native-secret", None, "conversation-secret", "message-secret", None, None)
    text = json.dumps(redacted_finding(CoverageFinding(item, "unresolved")))
    for forbidden in ("private-name", "native-secret", "conversation-secret", "message-secret", "raw/ChatGPT"):
        assert forbidden not in text


def test_summary_lists_sources_even_without_evidence():
    assert summarize_findings([])["sources"] == KNOWN_PLATFORMS


def test_public_policy_has_bounded_unique_nonsecret_rules():
    rules = load_policy()
    keys = [(rule["source"], rule["representation_kind"]) for rule in rules]
    assert len(keys) == len(set(keys))
    text = json.dumps(rules)
    assert "*" not in text
    assert "/Users/" not in text
    assert "http" not in text


def test_unmatched_class_stays_unresolved():
    item = RepresentationEvidence("Gemini CLI", "default", "new_unknown_shape", "raw/Gemini CLI/output", None, None, None, None, None, None)
    [finding] = reconcile_asset_coverage([item], pd.DataFrame(), pd.DataFrame(), load_policy())
    assert finding.status == "unresolved"


def test_gemini_cli_tool_output_spill_is_operational():
    item = RepresentationEvidence("Gemini CLI", "default", "tool_output_record", "raw/Gemini CLI/tool-outputs/x.txt", None, None, None, None, None, None)
    [finding] = reconcile_asset_coverage([item], pd.DataFrame(), pd.DataFrame(), load_policy())
    assert finding.status == "excluded"
    assert finding.policy_disposition == "operational"


@pytest.mark.parametrize("relative,kind,disposition", [
    ("background-processes/process.log", "cli_background_log", "operational"),
    ("bin/tool", "cli_bundled_binary", "cache"),
    ("logs.json.invalid_json.1.bak", "cli_recovery_backup", "operational"),
])
def test_gemini_cli_non_session_files_are_bounded_exclusions(
    tmp_path, relative, kind, disposition
):
    data = tmp_path / "data"
    path = data / "raw" / "Gemini CLI" / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"operational")
    [item] = inventory_preserved_session_assets(data)
    assert item.representation_kind == kind
    [finding] = reconcile_asset_coverage([item], pd.DataFrame(), pd.DataFrame(), load_policy())
    assert finding.status == "excluded"
    assert finding.policy_disposition == disposition


def test_native_file_record_reconciles_by_source_and_native_id():
    item = RepresentationEvidence("DeepSeek", "default", "native_file_record", "merged/DeepSeek/conversations/x", "file-1", None, "c", "m", None, "input")
    assets = pd.DataFrame({"source": ["deepseek"], "asset_id": ["file-1"], "asset_path": [None]})
    [finding] = reconcile_asset_coverage([item], assets, pd.DataFrame(), load_policy())
    assert finding.status == "covered"


def test_antigravity_explicit_artifact_record_is_eligible(tmp_path):
    data = tmp_path / "data"
    path = data / "raw" / "Antigravity CLI" / "brain" / "conv" / ".system_generated" / "logs" / "transcript.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "step_index": 2, "type": "PLANNER_RESPONSE", "source": "MODEL",
        "tool_calls": [{"name": "write_to_file", "args": {
            "TargetFile": "report.md", "CodeContent": "report",
            "ArtifactMetadata": {"UserFacing": True},
        }}],
    }) + "\n")
    evidence = inventory_preserved_session_assets(data)
    item = next(x for x in evidence if x.representation_kind == "generated_artifact_record")
    assert item.observed_role == "output"
    assert item.message_id == "conv_step_2"
    [finding] = reconcile_asset_coverage([item], pd.DataFrame(), pd.DataFrame())
    assert finding.status == "eligible_uncovered"
