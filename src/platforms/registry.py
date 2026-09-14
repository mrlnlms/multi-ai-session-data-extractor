"""Canonical platform registry shared by workflows and presentation layers."""

from dataclasses import dataclass

KNOWN_PLATFORMS: list[str] = [
    "ChatGPT",
    "Claude.ai",
    "Gemini",
    "NotebookLM",
    "Qwen",
    "DeepSeek",
    "Perplexity",
    "Grok",
    "Kimi",
    "Claude Code",
    "Codex",
    "Gemini CLI",
    "Antigravity CLI",
]

SCRIPT_PREFIX: dict[str, str] = {
    "ChatGPT": "chatgpt",
    "Claude.ai": "claude",
    "Gemini": "gemini",
    "NotebookLM": "notebooklm",
    "Qwen": "qwen",
    "DeepSeek": "deepseek",
    "Perplexity": "perplexity",
    "Grok": "grok",
    "Kimi": "kimi",
    "Claude Code": "claude-code",
    "Codex": "codex",
    "Gemini CLI": "gemini-cli",
    "Antigravity CLI": "antigravity-cli",
}

PLATFORM_COMMAND_PACKAGES: dict[str, str] = {
    "ChatGPT": "src.platforms.chatgpt.commands",
    "Claude.ai": "src.platforms.claude_ai.commands",
    "Gemini": "src.platforms.gemini.commands",
    "NotebookLM": "src.platforms.notebooklm.commands",
    "Perplexity": "src.platforms.perplexity.commands",
    "DeepSeek": "src.platforms.deepseek.commands",
    "Qwen": "src.platforms.qwen.commands",
    "Grok": "src.platforms.grok.commands",
    "Kimi": "src.platforms.kimi.commands",
    "Claude Code": "src.platforms.claude_code.commands",
    "Codex": "src.platforms.codex.commands",
    "Gemini CLI": "src.platforms.gemini_cli.commands",
    "Antigravity CLI": "src.platforms.antigravity_cli.commands",
}

WEB_PLATFORMS = frozenset({
    "ChatGPT", "Claude.ai", "Gemini", "NotebookLM", "Qwen", "DeepSeek",
    "Perplexity", "Grok", "Kimi",
})


@dataclass(frozen=True)
class PlatformAccountMetadata:
    """Filesystem compatibility metadata for observable web accounts."""

    registry_key: str
    profile_prefix: str
    fallback_keys: tuple[str, ...] = ("default",)
    legacy_default_profiles: tuple[str, ...] = ()
    historical_archive_root: str | None = None


@dataclass(frozen=True)
class AccountExecutionCapability:
    """Existing public flags used to select one web account."""

    login_argument: str
    sync_argument: str
    accepts_dynamic_keys: bool


PLATFORM_ACCOUNT_CAPABILITIES: dict[str, AccountExecutionCapability] = {
    "ChatGPT": AccountExecutionCapability("--profile", "--account", True),
    "Claude.ai": AccountExecutionCapability("--profile", "--profile", True),
    "Gemini": AccountExecutionCapability("--account", "--account", True),
    "NotebookLM": AccountExecutionCapability("--account", "--account", True),
    "Qwen": AccountExecutionCapability("--account", "--account", True),
    "DeepSeek": AccountExecutionCapability("--account", "--account", True),
    "Perplexity": AccountExecutionCapability("--account", "--account", True),
    "Grok": AccountExecutionCapability("--account", "--account", True),
    "Kimi": AccountExecutionCapability("--account", "--account", True),
}


PLATFORM_ACCOUNT_METADATA: dict[str, PlatformAccountMetadata] = {
    "ChatGPT": PlatformAccountMetadata("chatgpt", "chatgpt-profile-"),
    "Claude.ai": PlatformAccountMetadata("claude_ai", "claude-ai-profile-"),
    "Gemini": PlatformAccountMetadata("gemini", "gemini-profile-", ("1", "2", "3")),
    "NotebookLM": PlatformAccountMetadata(
        "notebooklm",
        "notebooklm-profile-",
        ("1", "2", "3"),
        historical_archive_root="notebooklm-snapshots",
    ),
    "Qwen": PlatformAccountMetadata("qwen", "qwen-profile-"),
    "DeepSeek": PlatformAccountMetadata("deepseek", "deepseek-profile-"),
    "Perplexity": PlatformAccountMetadata(
        "perplexity", "perplexity-profile-", legacy_default_profiles=("perplexity-profile",)
    ),
    "Grok": PlatformAccountMetadata("grok", "grok-profile-"),
    "Kimi": PlatformAccountMetadata("kimi", "kimi-profile-"),
}

SOURCE_TO_CATALOG_PLATFORM: dict[str, str] = {
    metadata.registry_key: platform
    for platform, metadata in PLATFORM_ACCOUNT_METADATA.items()
}

assert set(PLATFORM_ACCOUNT_METADATA) == set(WEB_PLATFORMS)
assert set(PLATFORM_ACCOUNT_CAPABILITIES) == set(WEB_PLATFORMS)
assert len(SOURCE_TO_CATALOG_PLATFORM) == len(PLATFORM_ACCOUNT_METADATA)
