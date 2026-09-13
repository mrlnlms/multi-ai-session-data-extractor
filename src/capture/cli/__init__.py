"""CLI sources (Claude Code, Codex, Gemini CLI, Antigravity CLI) — captura local de filesystem.

Diferente das 7 plataformas web (Playwright + batchexecute/API), CLIs lê
direto de pastas locais (~/.claude/projects, ~/.codex/sessions, ~/.gemini/tmp,
~/.gemini/antigravity-cli).

Modulo `copy.py` faz cópia incremental pra `data/raw/<source>/`.
"""
