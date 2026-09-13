from pathlib import Path

import pytest

from src.runtime.project import find_project_root


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_project_root_from_nested_module():
    module = PROJECT_ROOT / "src" / "platforms" / "chatgpt" / "commands" / "sync.py"
    assert find_project_root(module) == PROJECT_ROOT


def test_project_root_does_not_depend_on_legacy_scripts_directory():
    assert not (PROJECT_ROOT / "scripts").exists()
    assert find_project_root(PROJECT_ROOT / "src" / "workflows" / "unify.py") == PROJECT_ROOT


def test_find_project_root_rejects_unrelated_tree(tmp_path: Path):
    with pytest.raises(RuntimeError, match="project root"):
        find_project_root(tmp_path)
