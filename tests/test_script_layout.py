from pathlib import Path

import pytest

from dashboard.data import KNOWN_PLATFORMS, SCRIPT_PREFIX
from dashboard.sync import WEB_PLATFORMS, parse_command, sync_command


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


@pytest.mark.parametrize("platform", KNOWN_PLATFORMS)
def test_supported_source_has_root_sync_and_parse_entrypoints(platform: str):
    prefix = SCRIPT_PREFIX[platform]
    assert (SCRIPTS_DIR / f"{prefix}-sync.py").is_file()
    assert (SCRIPTS_DIR / f"{prefix}-parse.py").is_file()


@pytest.mark.parametrize("platform", sorted(WEB_PLATFORMS))
def test_web_source_has_root_login_entrypoint(platform: str):
    prefix = SCRIPT_PREFIX[platform]
    assert (SCRIPTS_DIR / f"{prefix}-login.py").is_file()


@pytest.mark.parametrize(
    "filename",
    [
        "headless-pipeline.py",
        "manual-saves-sync.py",
        "serve-qmds.sh",
        "unify-parquets.py",
    ],
)
def test_cross_platform_operational_entrypoint_stays_at_root(filename: str):
    assert (SCRIPTS_DIR / filename).is_file()


def test_root_contains_no_probe_scripts():
    assert not list(SCRIPTS_DIR.glob("*-probe-*.py"))


def test_no_python_cache_is_tracked():
    tracked = (PROJECT_ROOT / ".git").is_dir()
    if not tracked:
        pytest.skip("tracked-file assertion requires a Git checkout")

    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "scripts/**/__pycache__/*", "scripts/__pycache__/*"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""


@pytest.mark.parametrize("platform", KNOWN_PLATFORMS)
def test_dashboard_resolves_every_sync_entrypoint(platform: str):
    command = sync_command(platform)
    assert command is not None
    assert Path(command[1]).is_file()


@pytest.mark.parametrize("platform", sorted(WEB_PLATFORMS))
def test_dashboard_resolves_every_web_parse_entrypoint(platform: str):
    command = parse_command(platform)
    assert command is not None
    assert Path(command[1]).is_file()
