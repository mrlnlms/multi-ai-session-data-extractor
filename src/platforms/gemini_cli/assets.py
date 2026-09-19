"""Explicitly empty Gemini CLI asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("gemini_cli", "gemini_cli_empty", require_empty=True)
