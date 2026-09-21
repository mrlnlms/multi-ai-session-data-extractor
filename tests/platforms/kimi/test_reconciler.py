import json

from src.platforms.kimi.reconciler import run_reconciliation


class _EmptyProjection:
    assets = ()


class _VaultReaderStub:
    def projection_for(self, source, account_id):
        assert source == "kimi"
        return _EmptyProjection()


def _write_discovery(root, ids):
    root.mkdir(parents=True, exist_ok=True)
    (root / "discovery_ids.json").write_text(
        json.dumps([{"id": item} for item in ids]), encoding="utf-8"
    )


def test_reconcile_preserves_nested_current_and_previous_assets(tmp_path):
    raw = tmp_path / "raw"
    previous = tmp_path / "previous"
    merged = tmp_path / "merged"
    _write_discovery(raw, [])
    _write_discovery(previous, [])

    current_files = {
        "chat-a/file-1.pdf": b"current-one",
        "chat-b/file-2.png": b"current-two",
    }
    for relative, content in current_files.items():
        path = raw / "assets" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    previous_file = previous / "assets/chat-old/file-3.txt"
    previous_file.parent.mkdir(parents=True, exist_ok=True)
    previous_file.write_bytes(b"previous-only")

    run_reconciliation(raw, merged, previous_merged=previous)
    run_reconciliation(raw, merged, previous_merged=previous)

    expected = {**current_files, "chat-old/file-3.txt": b"previous-only"}
    for relative, content in expected.items():
        assert (merged / "assets" / relative).read_bytes() == content


def test_vault_reader_does_not_copy_raw_assets_into_merged(tmp_path):
    raw = tmp_path / "raw"
    merged = tmp_path / "merged"
    _write_discovery(raw, [])
    binary = raw / "assets" / "chat-a" / "attachment.bin"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"preserved")

    run_reconciliation(raw, merged, asset_reader=_VaultReaderStub())

    assert not (merged / "assets" / "chat-a" / "attachment.bin").exists()
