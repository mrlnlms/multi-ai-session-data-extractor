from pathlib import Path
import ast

import pytest

from src.platforms.registry import KNOWN_PLATFORMS
from src.workflows.execution import WEB_PLATFORMS, parse_command, sync_command


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def test_legacy_scripts_directory_is_absent():
    """Executable Python interfaces belong to importable modules under src."""
    assert not (PROJECT_ROOT / "scripts").exists()


def test_streamlit_entrypoint_lives_with_dashboard_package():
    assert (PROJECT_ROOT / "dashboard" / "app.py").is_file()
    assert not (PROJECT_ROOT / "dashboard.py").exists()


def test_environment_generated_skill_directories_are_ignored():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text().splitlines()
    assert ".agents/" in gitignore
    assert ".claude/" in gitignore


@pytest.mark.parametrize("module", ("headless", "manual_saves", "serve_reports", "unify"))
def test_cross_platform_command_is_importable(module: str):
    path = PROJECT_ROOT / "src" / "workflows" / f"{module}.py"
    assert path.is_file()
    assert 'if __name__ == "__main__"' in path.read_text()


def test_exceptional_operation_is_importable():
    path = PROJECT_ROOT / "src" / "operations" / "dvc_gc.py"
    assert path.is_file()
    assert 'if __name__ == "__main__"' in path.read_text()


def test_generic_tools_namespace_is_absent():
    assert not (PROJECT_ROOT / "src" / "tools").exists()


def test_src_is_independent_from_presentation_frameworks():
    offenders = []
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "streamlit" or name.startswith("dashboard") for name in names):
                offenders.append(path.relative_to(PROJECT_ROOT))
                break
    assert offenders == []


def test_dashboard_does_not_import_mutating_workflow_execution_primitives():
    forbidden = {
        "acquire_pipeline_lock", "release_pipeline_lock", "run_sync_streaming",
        "run_unify_streaming", "run_quarto_streaming", "run_publish_streaming",
    }
    offenders = []
    for path in (PROJECT_ROOT / "dashboard").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "src.workflows.execution"
                and any(alias.name in forbidden for alias in node.names)
            ):
                offenders.append(path.relative_to(PROJECT_ROOT))
                break
    assert offenders == []


def test_operational_command_map_covers_nonroutine_commands():
    command_map = (PROJECT_ROOT / "docs" / "operations" / "commands.md").read_text()
    for module in (
        "src.workflows.manual_saves",
        "src.workflows.serve_reports",
        "src.capture.cli.snapshot",
        "src.operations.dvc_gc",
    ):
        assert module in command_map


def test_obsolete_maintenance_directory_is_absent():
    assert not (PROJECT_ROOT / "src" / "maintenance").exists()


def test_maintained_python_does_not_invoke_scripts_workflows():
    roots = (PROJECT_ROOT / "src", PROJECT_ROOT / "dashboard")
    offenders = []
    for root in roots:
        for path in root.rglob("*.py"):
            if "scripts/workflows/" in path.read_text():
                offenders.append(path.relative_to(PROJECT_ROOT))
    assert offenders == []


def test_layout_contract_covers_every_known_platform():
    assert set(PLATFORM_ACTIONS) == set(KNOWN_PLATFORMS)
    assert set(PLATFORM_PACKAGE) == set(KNOWN_PLATFORMS)
    assert MIGRATED_PLATFORMS == set(KNOWN_PLATFORMS)


def test_web_platforms_are_exactly_platforms_with_login():
    expected = {name for name, actions in PLATFORM_ACTIONS.items() if "login" in actions}
    assert expected == set(WEB_PLATFORMS)


def test_horizontal_source_namespaces_are_absent():
    for namespace in ("extractors", "parsers", "reconcilers"):
        assert not (PROJECT_ROOT / "src" / namespace).exists()


def test_no_legacy_root_entrypoints():
    assert not list(PROJECT_ROOT.glob("*-login.py"))
    assert not list(PROJECT_ROOT.glob("*-sync.py"))
    assert not list(PROJECT_ROOT.glob("*-parse.py"))


def test_recovery_directory_is_not_used_for_platform_imports():
    recovery_dir = PROJECT_ROOT / "src" / "recovery"
    if recovery_dir.exists():
        assert not list(recovery_dir.glob("notebooklm*.py"))


def test_probes_live_inside_platform_directories():
    assert not (PROJECT_ROOT / "src" / "probes").exists()


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
