import json
from pathlib import Path

import pytest

from src.account_catalog import legacy_account_id, load_account_catalog
from src.operations.migrate_account_identity import apply_migration, plan_migration


def _write_v1(path: Path, records: list[tuple[str, str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 1,
        "accounts": [{
            "account_id": account_id,
            "platform": platform,
            "technical_key": key,
            "lifecycle_status": "historical" if key.startswith("archive:") else "active",
            "created_at": "2026-09-13T00:00:00Z",
            "updated_at": "2026-09-13T00:00:00Z",
        } for account_id, platform, key in records],
    }))


def _paths(tmp_path, records):
    catalog = tmp_path / "data/accounts/catalog.json"
    _write_v1(catalog, records)
    registry = tmp_path / ".storage/accounts.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"qwen": {"default": "owner@example.test"}}))
    return dict(
        catalog_path=catalog,
        raw_root=tmp_path / "data/raw",
        merged_root=tmp_path / "data/merged",
        external_root=tmp_path / "data/external",
        registry_path=registry,
    )


def test_plan_preserves_uuid_and_moves_default_contents(tmp_path):
    account_id = legacy_account_id("Qwen", "default")
    paths = _paths(tmp_path, [(account_id, "Qwen", "default")])
    raw = paths["raw_root"] / "Qwen"
    raw.mkdir(parents=True)
    (raw / "conversation.json").write_text("preserved")
    plan = plan_migration(**paths)
    assert plan.after.records[0].account_id == account_id
    assert plan.after.records[0].email == "owner@example.test"
    assert plan.moves[0].destination == raw / f"account-{account_id}" / "conversation.json"
    assert (raw / "conversation.json").exists()


def test_apply_moves_numbered_tree_and_writes_v2_last(tmp_path):
    account_id = legacy_account_id("Gemini", "2")
    paths = _paths(tmp_path, [(account_id, "Gemini", "2")])
    source = paths["merged_root"] / "Gemini/account-2"
    source.mkdir(parents=True)
    (source / "item.json").write_text("preserved")
    plan = plan_migration(**paths)
    apply_migration(plan, catalog_path=paths["catalog_path"])
    destination = paths["merged_root"] / "Gemini" / f"account-{account_id}"
    assert (destination / "item.json").read_text() == "preserved"
    catalog = load_account_catalog(paths["catalog_path"])
    assert not catalog.requires_identity_migration
    assert catalog.records[0].account_id == account_id


def test_historical_archive_is_preserved_under_uuid(tmp_path):
    account_id = legacy_account_id("NotebookLM", "archive:former-work")
    paths = _paths(tmp_path, [(account_id, "NotebookLM", "archive:former-work")])
    source = paths["external_root"] / "notebooklm-snapshots/Former Work"
    source.mkdir(parents=True)
    (source / "archive.json").write_text("preserved")
    plan = plan_migration(**paths)
    assert plan.moves == ((type(plan.moves[0]))(
        source,
        paths["external_root"] / "notebooklm-snapshots" / f"account-{account_id}",
    ),)
    apply_migration(plan, catalog_path=paths["catalog_path"])
    metadata = plan.moves[0].destination / "archive_metadata.json"
    assert json.loads(metadata.read_text()) == {"archive_key": "former-work"}


def test_destination_collision_aborts_without_changes(tmp_path):
    account_id = legacy_account_id("Gemini", "2")
    paths = _paths(tmp_path, [(account_id, "Gemini", "2")])
    source = paths["raw_root"] / "Gemini/account-2"
    destination = paths["raw_root"] / "Gemini" / f"account-{account_id}"
    source.mkdir(parents=True)
    destination.mkdir()
    with pytest.raises(ValueError, match="destination already exists"):
        plan_migration(**paths)
    assert source.exists()
    assert load_account_catalog(paths["catalog_path"]).requires_identity_migration


def test_catalog_write_failure_rolls_paths_back(tmp_path, monkeypatch):
    account_id = legacy_account_id("Gemini", "2")
    paths = _paths(tmp_path, [(account_id, "Gemini", "2")])
    source = paths["raw_root"] / "Gemini/account-2"
    source.mkdir(parents=True)
    plan = plan_migration(**paths)
    monkeypatch.setattr(
        "src.operations.migrate_account_identity.write_account_catalog_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("stale")),
    )
    with pytest.raises(ValueError, match="stale"):
        apply_migration(plan, catalog_path=paths["catalog_path"])
    assert source.exists()
    assert not plan.moves[0].destination.exists()
