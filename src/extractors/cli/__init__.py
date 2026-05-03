"""CLI sources (Claude Code, Codex, Gemini CLI) — captura local de filesystem.

Diferente das 7 plataformas web (Playwright + batchexecute/API), CLIs lê
direto de pastas locais (~/.claude/projects, ~/.codex/sessions, ~/.gemini/tmp).

Modulo `copy.py` faz cópia incremental pra `data/raw/<source>/`.
"""
