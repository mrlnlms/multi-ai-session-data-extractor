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
    codex = data / "raw" / "Codex" / "rollout.jsonl"
    codex.write_text(json.dumps({"type": "response_item", "payload": {
        "type": "message", "content": [{"type": "input_image", "image_url": "data:image/png;base64,YWJj"}],
    }}) + "\n")
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


def test_malformed_session_evidence_is_never_silently_ignored(tmp_path):
    data = tmp_path / "data"
    path = data / "raw" / "Codex" / "broken.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not-json\n")
    evidence = inventory_preserved_session_assets(data)
    assert any(item.representation_kind == "malformed_evidence" for item in evidence)


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
    item = RepresentationEvidence("Gemini CLI", "default", "tool_output_record", "raw/Gemini CLI/output", None, None, None, None, None, None)
    [finding] = reconcile_asset_coverage([item], pd.DataFrame(), pd.DataFrame(), load_policy())
    assert finding.status == "unresolved"


def test_native_file_record_reconciles_by_source_and_native_id():
    item = RepresentationEvidence("DeepSeek", "default", "native_file_record", "merged/DeepSeek/conversations/x", "file-1", None, "c", "m", None, "input")
    assets = pd.DataFrame({"source": ["deepseek"], "asset_id": ["file-1"], "asset_path": [None]})
    [finding] = reconcile_asset_coverage([item], assets, pd.DataFrame(), load_policy())
    assert finding.status == "covered"
