import keyword
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_script_layout import (
    MIGRATED_PLATFORMS,
    PLATFORM_ACTIONS,
    PLATFORM_PACKAGE,
    PLATFORM_TOOLS,
    SCRIPT_PREFIX,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLATFORMS_DIR = PROJECT_ROOT / "src" / "platforms"


@pytest.mark.parametrize("source_id", sorted(PLATFORM_PACKAGE.values()))
def test_platform_package_id_is_a_python_identifier(source_id: str):
    assert source_id.isidentifier()
    assert not keyword.iskeyword(source_id)
    assert "-" not in source_id


@pytest.mark.parametrize("platform", sorted(MIGRATED_PLATFORMS))
def test_migrated_platform_has_one_complete_source_package(platform: str):
    package_dir = PLATFORMS_DIR / PLATFORM_PACKAGE[platform]
    commands_dir = package_dir / "commands"

    assert (package_dir / "__init__.py").is_file()
    assert (commands_dir / "__init__.py").is_file()
    for action in PLATFORM_ACTIONS[platform]:
        assert (commands_dir / f"{action.replace('-', '_')}.py").is_file()
    for tool in PLATFORM_TOOLS.get(platform, set()):
        assert (commands_dir / f"{tool.replace('-', '_')}.py").is_file()


@pytest.mark.parametrize("platform", sorted(MIGRATED_PLATFORMS))
def test_migrated_platform_has_no_parallel_script_tree(platform: str):
    legacy_dir = PROJECT_ROOT / "scripts" / "platform" / SCRIPT_PREFIX[platform]
    assert not legacy_dir.exists()


@pytest.mark.parametrize(
    ("platform", "command"),
    [
        (platform, command)
        for platform in sorted(MIGRATED_PLATFORMS)
        for command in sorted(PLATFORM_ACTIONS[platform] | PLATFORM_TOOLS.get(platform, set()))
    ],
)
def test_platform_command_module_accepts_help(platform: str, command: str):
    module = command.replace("-", "_")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            f"src.platforms.{PLATFORM_PACKAGE[platform]}.commands.{module}",
            "--help",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
