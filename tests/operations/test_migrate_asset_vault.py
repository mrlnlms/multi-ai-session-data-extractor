from __future__ import annotations

import json
import stat

import pytest

from src.operations import migrate_asset_vault
from src.operations.migrate_asset_vault import create_plan, load_plan, run_plan
from src.operations.verify_asset_vault import restore_vault, verify_vault
from tests.assets.test_backfill import _write_inputs


@pytest.fixture
def planned_gemini(tmp_path, monkeypatch):
    inputs = _write_inputs(tmp_path)
    monkeypatch.setattr(migrate_asset_vault, "SOURCE_ORDER", ("gemini",))
    plan_path = tmp_path / "migration-plan.json"
    plan = create_plan(inputs.data_root, plan_path)
    return inputs, plan_path, plan


def test_plan_is_checksummed_read_only_and_never_overwritten(planned_gemini):
    inputs, plan_path, plan = planned_gemini

    assert load_plan(plan_path) == plan
    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o444
    assert plan["sources"][0]["expected"] == {
        "asset_count": 2,
        "link_count": 1,
        "available_count": 1,
        "message_path_count": 1,
    }
    with pytest.raises(FileExistsError):
        create_plan(inputs.data_root, plan_path)


def test_tampered_plan_and_changed_input_are_rejected(planned_gemini):
    inputs, plan_path, plan = planned_gemini
    plan_path.chmod(0o644)
    value = json.loads(plan_path.read_text())
    value["sources"][0]["expected"]["asset_count"] = 9
    plan_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="checksum"):
        load_plan(plan_path)

    clean_path = plan_path.with_name("clean-plan.json")
    create_plan(inputs.data_root, clean_path)
    inputs.messages_path.chmod(0o644)
    inputs.messages_path.write_bytes(inputs.messages_path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="changed after planning"):
        run_plan(clean_path, plan_path.parent / "temporary" / "assets")


def test_run_is_idempotent_refuses_canonical_and_restores_clean_root(planned_gemini):
    inputs, plan_path, _ = planned_gemini
    with pytest.raises(PermissionError, match="--apply-canonical"):
        run_plan(plan_path, inputs.data_root / "assets")
    with pytest.raises(ValueError, match="named 'assets'"):
        run_plan(plan_path, plan_path.parent / "not-the-compatible-name")

    vault_root = plan_path.parent / "migration" / "assets"
    first = run_plan(plan_path, vault_root)
    records = next(vault_root.glob("scopes/gemini/*/records.jsonl"))
    log = records.read_bytes()
    second = run_plan(plan_path, vault_root)

    assert second == first
    assert records.read_bytes() == log
    assert first["verification"]["sources"] == ["gemini"]
    assert first["sources"][0]["asset_count"] == 2

    restored = plan_path.parent / "restore" / "assets"
    restored_report = restore_vault(vault_root, restored)
    assert restored_report == verify_vault(restored)
    assert restored_report == first["verification"]
    assert list(restored.glob("scopes/gemini/*/state.json"))
    assert not list(restored.rglob("asset-projections"))

    with pytest.raises(ValueError, match="empty"):
        restore_vault(vault_root, restored)
