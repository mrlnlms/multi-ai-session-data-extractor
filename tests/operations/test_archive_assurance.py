import json
from pathlib import Path

from src.operations.archive_assurance import read_assurance, write_assurance


def _fixture(root: Path) -> None:
    pointer = root / "data/raw.dvc"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("outs:\n- md5: abc\n")
    raw = root / "data/raw/ChatGPT/a.json"
    raw.parent.mkdir(parents=True)
    raw.write_text("{}")


def test_receipt_is_reusable_until_local_data_changes(tmp_path: Path) -> None:
    _fixture(tmp_path)
    write_assurance(tmp_path, git_head="abc", method="verified_cloud")

    assert read_assurance(tmp_path, git_head="abc").status == "verified"
    assert read_assurance(tmp_path, git_head="different").status == "verified"

    (tmp_path / "data/raw/ChatGPT/a.json").write_text('{"new": 1}')
    assert read_assurance(tmp_path, git_head="abc").status == "changed"


def test_receipt_records_scope_without_private_contents(tmp_path: Path) -> None:
    _fixture(tmp_path)
    write_assurance(tmp_path, git_head="abc", method="completed_push")

    payload = json.loads((tmp_path / ".runtime/archive-assurance.json").read_text())
    assert payload["git_head"] == "abc"
    assert payload["method"] == "completed_push"
    assert "data/raw/ChatGPT/a.json" not in json.dumps(payload)


def test_status_never_runs_dvc_or_network(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    write_assurance(tmp_path, git_head="abc", method="verified_cloud")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("status must not spawn a process")

    monkeypatch.setattr("subprocess.run", forbidden)
    assert read_assurance(tmp_path).status == "verified"
