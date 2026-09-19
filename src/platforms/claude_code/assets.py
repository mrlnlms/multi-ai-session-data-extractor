"""Read-only Claude Code inline-image asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("claude_code", "cli_inline")
