from pathlib import Path

from src.reconciliation.files import link_or_copy


def test_link_or_copy_creates_hardlink(tmp_path: Path) -> None:
    source = tmp_path / "raw" / "asset.bin"
    destination = tmp_path / "merged" / "nested" / "asset.bin"
    source.parent.mkdir()
    source.write_bytes(b"immutable asset")

    assert link_or_copy(source, destination) is True

    assert destination.read_bytes() == source.read_bytes()
    assert destination.samefile(source)


def test_link_or_copy_leaves_existing_destination_untouched(tmp_path: Path) -> None:
    source = tmp_path / "raw.bin"
    destination = tmp_path / "merged.bin"
    source.write_bytes(b"new")
    destination.write_bytes(b"preserved")

    assert link_or_copy(source, destination) is False

    assert destination.read_bytes() == b"preserved"
    assert not destination.samefile(source)


def test_link_or_copy_falls_back_to_copy(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "raw.bin"
    destination = tmp_path / "nested" / "merged.bin"
    source.write_bytes(b"portable asset")

    def unavailable(_source: Path, _destination: Path) -> None:
        raise OSError("hardlinks unavailable")

    monkeypatch.setattr("src.reconciliation.files.os.link", unavailable)

    assert link_or_copy(source, destination) is True

    assert destination.read_bytes() == source.read_bytes()
    assert not destination.samefile(source)
