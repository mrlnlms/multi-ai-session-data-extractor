import json
import pytest
from src.extractors.cli.sanitize import sanitize_claude_settings


def test_redacts_anthropic_api_key_in_env():
    raw = json.dumps({
        "env": {"ANTHROPIC_API_KEY": "sk-ant-xxxx", "PATH": "/usr/bin"},
        "permissions": {"allow": ["Bash"]},
    })
    out = json.loads(sanitize_claude_settings(raw))
    assert out["env"]["ANTHROPIC_API_KEY"] == "<redacted>"
    assert out["env"]["PATH"] == "/usr/bin"  # unchanged
    assert out["permissions"] == {"allow": ["Bash"]}


def test_redacts_nested_keys_with_secret_in_mcpservers():
    raw = json.dumps({
        "mcpServers": {
            "github": {"env": {"GITHUB_TOKEN": "ghp_xxx", "BASE_URL": "https://api.github.com"}},
            "openai": {"env": {"OPENAI_SECRET_KEY": "sk-yyy"}},
        }
    })
    out = json.loads(sanitize_claude_settings(raw))
    assert out["mcpServers"]["github"]["env"]["GITHUB_TOKEN"] == "<redacted>"
    assert out["mcpServers"]["github"]["env"]["BASE_URL"] == "https://api.github.com"
    assert out["mcpServers"]["openai"]["env"]["OPENAI_SECRET_KEY"] == "<redacted>"


def test_handles_settings_without_env_field():
    raw = json.dumps({"permissions": {"allow": ["Bash"]}})
    out = json.loads(sanitize_claude_settings(raw))
    assert out == {"permissions": {"allow": ["Bash"]}}


def test_malformed_json_returns_none():
    out = sanitize_claude_settings("{not valid json")
    assert out is None
