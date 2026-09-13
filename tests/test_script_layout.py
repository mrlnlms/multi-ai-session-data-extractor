from pathlib import Path

import pytest

from dashboard.data import KNOWN_PLATFORMS, SCRIPT_PREFIX
from dashboard.sync import WEB_PLATFORMS, parse_command, sync_command


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
PLATFORM_ACTIONS = {
    "ChatGPT": {"login", "sync", "parse"},
    "Claude.ai": {"login", "sync", "parse"},
    "Gemini": {"login", "sync", "parse"},
    "NotebookLM": {"login", "sync", "parse"},
    "Qwen": {"login", "sync", "parse"},
    "DeepSeek": {"login", "sync", "parse"},
    "Perplexity": {"login", "sync", "parse"},
    "Grok": {"login", "sync", "parse"},
    "Kimi": {"login", "sync", "parse"},
    "Claude Code": {"sync", "parse"},
    "Codex": {"sync", "parse"},
    "Gemini CLI": {"sync", "parse"},
    "Antigravity CLI": {"sync", "parse"},
}
PLATFORM_TOOLS = {
    "Antigravity CLI": {"recover-legacy"},
}
WORKFLOW_FILES = {
    "copy-cli-data.py",
    "headless-pipeline.py",
    "manual-saves-sync.py",
    "serve-qmds.sh",
    "unify-parquets.py",
}


@pytest.mark.parametrize(
    ("platform", "action"),
    [(platform, action) for platform, actions in PLATFORM_ACTIONS.items() for action in sorted(actions)],
)
def test_supported_source_has_platform_entrypoint(platform: str, action: str):
    prefix = SCRIPT_PREFIX[platform]
    assert (SCRIPTS_DIR / "platform" / prefix / f"{action}.py").is_file()


@pytest.mark.parametrize(
    ("platform", "tool"),
    [(platform, tool) for platform, tools in PLATFORM_TOOLS.items() for tool in sorted(tools)],
)
def test_supported_source_has_platform_tool(platform: str, tool: str):
    prefix = SCRIPT_PREFIX[platform]
    assert (SCRIPTS_DIR / "platform" / prefix / f"{tool}.py").is_file()


@pytest.mark.parametrize("filename", sorted(WORKFLOW_FILES))
def test_cross_platform_entrypoint_lives_in_workflows(filename: str):
    assert (SCRIPTS_DIR / "workflows" / filename).is_file()


def test_scripts_root_contains_only_readme():
    assert {path.name for path in SCRIPTS_DIR.iterdir() if path.is_file()} == {"README.md"}


def test_layout_contract_covers_every_known_platform():
    assert set(PLATFORM_ACTIONS) == set(KNOWN_PLATFORMS)


def test_web_platforms_are_exactly_platforms_with_login():
    expected = {name for name, actions in PLATFORM_ACTIONS.items() if "login" in actions}
    assert expected == set(WEB_PLATFORMS)


def test_platform_directories_match_registered_prefixes():
    actual = {
        path.name
        for path in (SCRIPTS_DIR / "platform").iterdir()
        if path.is_dir()
    }
    assert actual == set(SCRIPT_PREFIX.values())


def test_no_legacy_root_entrypoints():
    assert not list(SCRIPTS_DIR.glob("*-login.py"))
    assert not list(SCRIPTS_DIR.glob("*-sync.py"))
    assert not list(SCRIPTS_DIR.glob("*-parse.py"))


def test_probes_live_inside_platform_directories():
    assert not (SCRIPTS_DIR / "probes").exists()
    for probes_dir in SCRIPTS_DIR.glob("platform/*/probes"):
        assert probes_dir.parent.name in SCRIPT_PREFIX.values()


def test_no_python_cache_is_tracked():
    if not (PROJECT_ROOT / ".git").is_dir():
        pytest.skip("tracked-file assertion requires a Git checkout")

    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "scripts/**/__pycache__/*"],
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
