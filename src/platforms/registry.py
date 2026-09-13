"""Canonical platform registry shared by workflows and presentation layers."""

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
