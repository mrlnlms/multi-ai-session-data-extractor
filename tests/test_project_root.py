from pathlib import Path

import pytest

from src.runtime.project import find_project_root


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_project_root_from_nested_script():
    script = PROJECT_ROOT / "scripts" / "platform" / "chatgpt" / "sync.py"
    assert find_project_root(script) == PROJECT_ROOT


def test_find_project_root_rejects_unrelated_tree(tmp_path: Path):
    with pytest.raises(RuntimeError, match="project root"):
        find_project_root(tmp_path)
