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
TOOL_FILES = {"prune-dvc-history.py"}
PLATFORM_PACKAGE = {
    "ChatGPT": "chatgpt",
    "Claude.ai": "claude_ai",
    "Gemini": "gemini",
    "NotebookLM": "notebooklm",
    "Qwen": "qwen",
    "DeepSeek": "deepseek",
    "Perplexity": "perplexity",
    "Grok": "grok",
    "Kimi": "kimi",
    "Claude Code": "claude_code",
    "Codex": "codex",
    "Gemini CLI": "gemini_cli",
    "Antigravity CLI": "antigravity_cli",
}
MIGRATED_PLATFORMS: set[str] = set(KNOWN_PLATFORMS)


@pytest.mark.parametrize(
    ("platform", "action"),
    [(platform, action) for platform, actions in PLATFORM_ACTIONS.items() for action in sorted(actions)],
)
def test_supported_source_has_platform_entrypoint(platform: str, action: str):
    source_id = PLATFORM_PACKAGE[platform]
    assert (
        PROJECT_ROOT / "src" / "platforms" / source_id / "commands" / f"{action}.py"
    ).is_file()


@pytest.mark.parametrize(
    ("platform", "tool"),
    [(platform, tool) for platform, tools in PLATFORM_TOOLS.items() for tool in sorted(tools)],
)
def test_supported_source_has_platform_tool(platform: str, tool: str):
    source_id = PLATFORM_PACKAGE[platform]
    module = tool.replace("-", "_")
    assert (
        PROJECT_ROOT / "src" / "platforms" / source_id / "commands" / f"{module}.py"
    ).is_file()


@pytest.mark.parametrize("filename", sorted(WORKFLOW_FILES))
def test_cross_platform_entrypoint_lives_in_workflows(filename: str):
    assert (SCRIPTS_DIR / "workflows" / filename).is_file()


@pytest.mark.parametrize("filename", sorted(TOOL_FILES))
def test_optional_operator_command_lives_in_tools(filename: str):
    assert (SCRIPTS_DIR / "tools" / filename).is_file()


def test_obsolete_maintenance_directory_is_absent():
    assert not (SCRIPTS_DIR / "maintenance").exists()


def test_scripts_root_contains_only_readme():
    assert {path.name for path in SCRIPTS_DIR.iterdir() if path.is_file()} == {"README.md"}


def test_layout_contract_covers_every_known_platform():
    assert set(PLATFORM_ACTIONS) == set(KNOWN_PLATFORMS)
    assert set(PLATFORM_PACKAGE) == set(KNOWN_PLATFORMS)
    assert MIGRATED_PLATFORMS == set(KNOWN_PLATFORMS)


def test_web_platforms_are_exactly_platforms_with_login():
    expected = {name for name, actions in PLATFORM_ACTIONS.items() if "login" in actions}
    assert expected == set(WEB_PLATFORMS)


def test_platform_directories_match_registered_prefixes():
    assert MIGRATED_PLATFORMS == set(KNOWN_PLATFORMS)
    assert not (SCRIPTS_DIR / "platform").exists()


def test_horizontal_source_namespaces_are_absent():
    for namespace in ("extractors", "parsers", "reconcilers"):
        assert not (PROJECT_ROOT / "src" / namespace).exists()


def test_no_legacy_root_entrypoints():
    assert not list(SCRIPTS_DIR.glob("*-login.py"))
    assert not list(SCRIPTS_DIR.glob("*-sync.py"))
    assert not list(SCRIPTS_DIR.glob("*-parse.py"))


def test_recovery_directory_is_not_used_for_platform_imports():
    recovery_dir = SCRIPTS_DIR / "recovery"
    if recovery_dir.exists():
        assert not list(recovery_dir.glob("notebooklm*.py"))


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
    assert command[1:3] == ["-m", f"src.platforms.{PLATFORM_PACKAGE[platform]}.commands.sync"]


@pytest.mark.parametrize("platform", sorted(WEB_PLATFORMS))
def test_dashboard_resolves_every_web_parse_entrypoint(platform: str):
    command = parse_command(platform)
    assert command is not None
    assert command[1:3] == ["-m", f"src.platforms.{PLATFORM_PACKAGE[platform]}.commands.parse"]
